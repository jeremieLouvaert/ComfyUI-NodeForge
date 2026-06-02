"""
Stage 2 -- test synthesis with the ref0 teeth-gate (self-verification-model.md
section 9.2, resolved this session to ref0 + example-filter).

Orchestration:
  1. ref0  = one reference impl (codegen.generate_ref0), in a context isolated
     from the check-author. Example-FILTERED (ref0_satisfies_examples): ref0 must
     satisfy every machine-checkable confirmed example before it is trusted as the
     specificity guard. If no ref0 satisfies the examples, the spec is
     bad/contradictory -> the caller escalates to Stage 1.
  2. mutants = mutate.build_operator_mutants(ref0) + optional LLM subtly-wrong
     mutants. Each must load + behaviorally differ from ref0 to be a teeth target.
  3. battery = generate_battery(spec) (reused verbatim from benchmark/generate.py)
     -> a module with CHECKS. evaluate_draw runs the whole battery once in the
     sandbox against ref0 + every mutant.
  4. KEEP a check iff it PASSES ref0 (specificity guard) AND FAILS >=1 mutant
     (teeth). Drop the rest.
  5. COVERAGE BAR: vet_battery loops draws until the kept checks COLLECTIVELY kill
     EVERY mutant, or the draw budget is spent (then unkilled mutants are surfaced
     as named residual risk).

Output: vetted battery (list of Check) + OPEN_QUESTIONS (carried to Stage-4
triage) + ref0 (reused as a Stage-4 candidate).
"""
import os
import sys
import re

from . import records, sandbox

# reuse the PROVEN battery generator verbatim
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(_REPO, "benchmark") not in sys.path:
    sys.path.insert(0, os.path.join(_REPO, "benchmark"))
import generate as _bench_generate   # benchmark/generate.py (generate_battery + SYSTEM_PROMPT)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _example_fixtures(spec):
    return [{"example_id": e.id, "input_spec": e.input_spec.to_dict(), "args": e.args or {}}
            for e in spec.examples]


def _check_names_in_report(rep):
    seen = []
    for r in rep.results:
        if r.check_name not in seen:
            seen.append(r.check_name)
    return seen


def _check_passed(rep, qualified_name, candidate_id):
    for r in rep.results:
        if r.check_name == qualified_name and r.candidate_id == candidate_id:
            return r.passed
    return False     # absent == not passed (candidate failed to load, etc.)


def _open_questions(battery_source):
    m = re.search(r"OPEN_QUESTIONS\s*=\s*\[(.*?)\]", battery_source, re.DOTALL)
    if not m:
        return []
    return re.findall(r'["\'](.*?)["\']', m.group(1))


def _single_check_source(battery_source, qualified_name):
    """Standalone source for one kept check: the whole battery module with CHECKS
    narrowed to that one function (so its module helpers stay in scope)."""
    fn = qualified_name.split(":", 1)[-1]
    return battery_source + f"\n\nCHECKS = [{fn}]\n"


def _run_battery_against(spec, battery_source, ref0, mutants, wall_s=60):
    cands = [{"id": "ref0", "source": ref0.source, "class_name": ref0.class_name, "origin": "ref0"}]
    for m in mutants:
        cands.append({"id": m.id, "source": m.source, "class_name": m.class_name, "origin": m.origin})
    job = {"job_id": "synth_battery", "mode": "run", "allow_gpu": False,
           "candidates": cands, "batteries": [{"id": "b", "source": battery_source}],
           "example_fixtures": _example_fixtures(spec)}
    return sandbox.run_job(job, wall_s=wall_s)


# ---------------------------------------------------------------------------
# example-filter for ref0
# ---------------------------------------------------------------------------
def ref0_satisfies_examples(spec, ref0, wall_s=30):
    """Run ref0 against the machine-checkable (literal) confirmed examples. Returns
    (ok, failing_ids). Relation/invariant examples are left to the generated
    battery (rule 2: don't recompute the whole op as a second impl)."""
    checks_src = _examples_as_battery(spec)
    if checks_src is None:
        return True, []
    job = {"job_id": "ref0_examplefilter", "mode": "run", "allow_gpu": False,
           "candidates": [{"id": "ref0", "source": ref0.source,
                           "class_name": ref0.class_name, "origin": "ref0"}],
           "batteries": [{"id": "ex", "source": checks_src}],
           "example_fixtures": _example_fixtures(spec)}
    rep = sandbox.run_job(job, wall_s=wall_s)
    if rep.load_errors:
        return False, [f"<ref0 load error: {rep.load_errors}>"]
    failing = [r.check_name for r in rep.results_for("ref0") if not r.passed]
    return (len(failing) == 0), failing


def _examples_as_battery(spec):
    """Turn the confirmed LITERAL examples into a minimal battery module so ref0
    can be example-filtered without a hand-written impl. Returns source or None."""
    fns, names = [], []
    for e in spec.examples:
        exp = e.expectation
        if exp.kind == "literal" and exp.literal is not None:
            fname = f"check_ex_{_san(e.id)}"
            names.append(fname)
            fns.append(_literal_check_fn(fname, e))
    if not fns:
        return None
    return ("import torch\nimport torch.nn.functional as F\n\n"
            "from nodeforge import fixtures as _fx\n\n"
            + "\n\n".join(fns)
            + "\n\nCHECKS = [" + ", ".join(names) + "]\nOPEN_QUESTIONS = []\n")


def _san(s):
    return re.sub(r"\W+", "_", str(s))


def _literal_check_fn(fname, example):
    inp = example.input_spec.to_dict()
    lit = example.expectation.literal
    args = example.args or {}
    return (
        f"def {fname}(NodeClass):\n"
        f"    import torch\n"
        f"    node = NodeClass()\n"
        f"    fn = getattr(node, NodeClass.FUNCTION)\n"
        f"    img = _fx.build({inp!r})\n"
        f"    ex_args = {args!r}\n"
        f"    spec = NodeClass.INPUT_TYPES().get('required', {{}})\n"
        f"    kwargs = {{}}\n"
        f"    for pname, pdef in spec.items():\n"
        f"        if pname == 'image' or (isinstance(pdef,(list,tuple)) and pdef and pdef[0]=='IMAGE'):\n"
        f"            kwargs[pname] = img\n"
        f"        elif pname in ex_args:\n"
        f"            kwargs[pname] = ex_args[pname]\n"
        f"        elif isinstance(pdef,(list,tuple)) and len(pdef)>1 and isinstance(pdef[1],dict) and 'default' in pdef[1]:\n"
        f"            kwargs[pname] = pdef[1]['default']\n"
        f"    out = fn(**kwargs)\n"
        f"    o0 = out[0] if isinstance(out,(tuple,list)) else out\n"
        f"    target = torch.tensor({lit!r}, dtype=torch.float32)\n"
        f"    try:\n"
        f"        t = target.expand_as(o0).float()\n"
        f"    except Exception:\n"
        f"        t = target.float()\n"
        f"    ok = bool(o0.float().shape == t.shape and torch.allclose(o0.float(), t, atol=2e-2))\n"
        f"    return ('{fname}', ok, 'literal example match')\n"
    )


# ---------------------------------------------------------------------------
# A3 graceful-degradation fallback battery (no LLM, no teeth): the confirmed
# examples + the output contract. Used only when the teeth-gate yields no checks,
# so the run reaches the human gate (flagged "limited verification") instead of a
# dead-end. The human + the before/after images are the oracle here.
# ---------------------------------------------------------------------------
def _contract_battery(spec):
    """Generic IMAGE-output contract checks (range [0,1], dtype float32, and shape
    preservation when the spec asserts it) as a battery module. Returns source or
    None when the node does not output an IMAGE."""
    rtypes = [str(t).upper() for t in (spec.return_types or [])]
    if "IMAGE" not in rtypes:
        return None
    pres = any(("shape" in str(x).lower() and ("equal" in str(x).lower() or "same" in str(x).lower()))
               for x in (list(spec.invariants) + [spec.contract or ""]))
    src = (
        "import torch\n"
        "from nodeforge import fixtures as _fx\n\n"
        "def _run(NodeClass):\n"
        "    node = NodeClass(); fn = getattr(node, NodeClass.FUNCTION)\n"
        "    img = _fx.build({'generator':'seeded_texture','params':{'h':16,'w':16}})\n"
        "    req = NodeClass.INPUT_TYPES().get('required', {})\n"
        "    kwargs = {}\n"
        "    for pname, pdef in req.items():\n"
        "        if pname=='image' or (isinstance(pdef,(list,tuple)) and pdef and pdef[0]=='IMAGE'):\n"
        "            kwargs[pname]=img\n"
        "        elif isinstance(pdef,(list,tuple)) and len(pdef)>1 and isinstance(pdef[1],dict) and 'default' in pdef[1]:\n"
        "            kwargs[pname]=pdef[1]['default']\n"
        "    out = fn(**kwargs)\n"
        "    o = out[0] if isinstance(out,(tuple,list)) else out\n"
        "    return img, o\n\n"
        "def check_contract_range(NodeClass):\n"
        "    _, o = _run(NodeClass)\n"
        "    return ('contract_range', bool(o.min()>=-1e-3 and o.max()<=1+1e-3), 'output in [0,1]')\n\n"
        "def check_contract_dtype(NodeClass):\n"
        "    _, o = _run(NodeClass)\n"
        "    return ('contract_dtype', bool(o.dtype==torch.float32), str(o.dtype))\n\n"
    )
    checks = ["check_contract_range", "check_contract_dtype"]
    if pres:
        src += (
            "def check_contract_shape(NodeClass):\n"
            "    img, o = _run(NodeClass)\n"
            "    return ('contract_shape', bool(tuple(o.shape)==tuple(img.shape)), f'{tuple(o.shape)} vs {tuple(img.shape)}')\n\n"
        )
        checks.append("check_contract_shape")
    src += "CHECKS = [" + ", ".join(checks) + "]\nOPEN_QUESTIONS = []\n"
    return src


def fallback_checks(spec):
    """A3: the no-teeth fallback battery as a list[Check] -- the confirmed literal
    examples (via _examples_as_battery) plus the IMAGE contract. teeth=[] (these
    kill no mutants by construction); they are the human-confirmed oracle + the
    contract, surfaced honestly as limited verification. Returns [] only when there
    is genuinely nothing to check (no literal examples and a non-IMAGE output)."""
    out = []
    ex_src = _examples_as_battery(spec)
    if ex_src:
        out.append(records.Check(name="confirmed_examples", source=ex_src,
                                 teeth=[], passes_ref0=True, vacuous=False))
    contract_src = _contract_battery(spec)
    if contract_src:
        out.append(records.Check(name="output_contract", source=contract_src,
                                 teeth=[], passes_ref0=True, vacuous=False))
    return out


# ---------------------------------------------------------------------------
# op-aware discriminating fixtures (A2): a spatially-structured op (halftone,
# dither, tiling, kernels) produces UNIFORM output on a solid/tiny input, so a
# mutant that breaks its grid/rotation/cell logic looks identical to ref0 there
# and valid_mutants drops it -- leaving zero teeth targets and a Stage-2 dead-end.
# Probing on structured, op-sized fixtures makes those mutants differ and survive.
# ---------------------------------------------------------------------------
_SIZE_WIDGET_RE = re.compile(r"dot|cell|tile|kernel|grid|radius|block|patch|step|size", re.I)


def _op_probe_size(spec):
    """Probe edge length large enough that a structured op shows structure: ~4x the
    largest cell/size-like INT widget default, clamped to [16, 48] (kept modest so
    the sandbox stays fast)."""
    sizes = []
    for section in ("required", "optional"):
        for name, pdef in (spec.input_types.get(section, {}) or {}).items():
            if not _SIZE_WIDGET_RE.search(str(name)):
                continue
            if isinstance(pdef, (list, tuple)) and pdef and pdef[0] == "INT":
                opts = pdef[1] if len(pdef) > 1 and isinstance(pdef[1], dict) else {}
                d = opts.get("default")
                if isinstance(d, (int, float)) and d > 0:
                    sizes.append(int(d))
    base = max(sizes) * 4 if sizes else 32
    return max(16, min(48, base))


def _discriminating_probes(spec):
    """Structured, op-sized fixtures (checkerboard + gradient + texture) so a
    spatial mutant differs from ref0 even when the confirmed examples are solid or
    tiny. Deterministic, no API. Returns [{example_id, input_spec, args}]."""
    n = _op_probe_size(spec)
    cell = max(2, n // 8)
    return [
        {"example_id": "_probe_checker",
         "input_spec": {"generator": "checkerboard", "params": {"cell": cell, "h": n, "w": n}}, "args": {}},
        {"example_id": "_probe_grad",
         "input_spec": {"generator": "gradient", "params": {"axis": "x", "h": n, "w": n}}, "args": {}},
        {"example_id": "_probe_tex",
         "input_spec": {"generator": "seeded_texture", "params": {"seed": 7, "h": n, "w": n}}, "args": {}},
    ]


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------
def valid_mutants(spec, ref0, mutants, wall_s=60):
    """Keep only mutants that LOAD and behaviorally DIFFER from ref0 on >=1 example
    fixture. A mutant equal to ref0 (e.g. an identity-corruption on an op that is
    already a near-identity at this fixture size) is un-killable and would make the
    coverage bar unreachable -- drop it. Returns (kept_mutants, dropped_ids)."""
    if not mutants:
        return [], []
    cands = [{"id": "ref0", "source": ref0.source, "class_name": ref0.class_name, "origin": "ref0"}]
    for m in mutants:
        cands.append({"id": m.id, "source": m.source, "class_name": m.class_name, "origin": m.origin})
    # A2: probe on the confirmed example fixtures AND op-sized structured probes, so
    # a spatial mutant that is invisible on a solid/tiny example still differs on a
    # structured probe and survives as a teeth target (keep a mutant if it differs
    # on ANY fixture).
    fixtures = _example_fixtures(spec) + _discriminating_probes(spec)
    job = {"job_id": "mutant_validate", "mode": "run", "allow_gpu": False,
           "candidates": cands, "batteries": [], "example_fixtures": fixtures}
    # batteries empty -> child still computes output_digests; but it early-returns
    # if no checks. Give it a trivial always-pass battery so it proceeds.
    job["batteries"] = [{"id": "_noop",
                         "source": "def check_noop(NodeClass):\n    return ('noop', True, '')\nCHECKS=[check_noop]\nOPEN_QUESTIONS=[]\n"}]
    rep = sandbox.run_job(job, wall_s=wall_s)
    ref0_dig = rep.output_digests.get("ref0", {})
    kept, dropped = [], []
    for m in mutants:
        if m.id in rep.load_errors:
            dropped.append(m.id)
            continue
        mdig = rep.output_digests.get(m.id, {})
        differs = any(mdig.get(k) != ref0_dig.get(k) for k in ref0_dig) or (mdig and not ref0_dig)
        if differs:
            kept.append(m)
        else:
            dropped.append(m.id)
    return kept, dropped


def evaluate_draw(spec, battery_src, ref0, mutants, wall_s=60):
    """Evaluate ONE generated battery draw against ref0 + mutants in the sandbox.

    Returns (kept_checks: [Check], open_questions: [str], battery_loaded: bool).
    A check is kept iff it PASSES ref0 AND FAILS >=1 mutant. Pure gate mechanic --
    no LLM -- so it is offline-testable with a pre-generated battery."""
    mutant_ids = [m.id for m in mutants]
    rep = _run_battery_against(spec, battery_src, ref0, mutants, wall_s=wall_s)
    if any(k.startswith("battery:") for k in rep.load_errors):
        return [], _open_questions(battery_src), False
    kept = []
    for cname in _check_names_in_report(rep):
        ref0_passed = _check_passed(rep, cname, "ref0")
        failed_mutants = [mid for mid in mutant_ids
                          if mid not in rep.load_errors and not _check_passed(rep, cname, mid)]
        if ref0_passed and failed_mutants:
            kept.append(records.Check(
                name=cname, source=_single_check_source(battery_src, cname),
                teeth=failed_mutants, passes_ref0=True, vacuous=False))
    return kept, _open_questions(battery_src), True


def vet_battery(spec, ref0, mutants, model="claude-sonnet-4-6", client=None,
                max_draws=4, wall_s=60, log=print):
    """The Stage-2 ref0 teeth-gate. Generates batteries until every mutant is
    killed by some kept check (coverage bar) or the draw budget is spent.

    Returns {kept_checks: [Check], open_questions: [str], unkilled_mutants: [id],
             ref0: Candidate, draws: int}."""
    # drop un-killable mutants (don't load, or don't differ from ref0) up front so
    # the coverage bar is reachable.
    mutants, dropped = valid_mutants(spec, ref0, mutants, wall_s=wall_s)
    if dropped:
        log(f"  dropped {len(dropped)} non-discriminating mutant(s): {dropped}")
    kept = {}
    open_qs = []
    mutant_ids = [m.id for m in mutants]
    killed = set()
    draws = 0
    seed = 0
    while draws < max_draws and len(killed) < len(mutant_ids):
        draws += 1
        try:
            battery_src, _usage = _bench_generate.generate_battery(
                spec.to_spec_string(), model=model, seed_hint=seed)
        except Exception as e:
            log(f"  draw {draws}: battery generation failed ({e}); retrying")
            seed += 1
            continue
        seed += 1
        draw_kept, draw_open, loaded = evaluate_draw(spec, battery_src, ref0, mutants, wall_s)
        open_qs = open_qs or draw_open
        if not loaded:
            log(f"  draw {draws}: battery failed to load; regenerating")
            continue
        for chk in draw_kept:
            if chk.name not in kept:
                kept[chk.name] = chk
                killed.update(chk.teeth)
        log(f"  draw {draws}: kept {len(kept)} checks, killed {len(killed)}/{len(mutant_ids)} mutants")

    unkilled = [m for m in mutant_ids if m not in killed]
    return {"kept_checks": list(kept.values()), "open_questions": open_qs,
            "unkilled_mutants": unkilled, "ref0": ref0, "draws": draws}

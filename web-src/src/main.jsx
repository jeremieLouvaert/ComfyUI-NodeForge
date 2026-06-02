import { app } from '/scripts/app.js'
import { api } from '/scripts/api.js'
import { createRoot } from 'react-dom/client'
import { App } from './App.jsx'
import './styles/global.css'

let rootInstance = null

app.registerExtension({
  name: 'NodeForge',
  async setup() {
    app.extensionManager.registerSidebarTab({
      id: 'nodeforge',
      icon: 'pi pi-wrench',
      title: 'NodeForge',
      tooltip: 'NodeForge — author a node',
      type: 'custom',
      render: (el) => {
        rootInstance = createRoot(el)
        rootInstance.render(<App api={api} />)
      },
      destroy: () => {
        if (rootInstance) {
          rootInstance.unmount()
          rootInstance = null
        }
      },
    })
  },
})

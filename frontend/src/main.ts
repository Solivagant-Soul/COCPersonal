import { createPinia } from 'pinia'
import { createApp } from 'vue'
import 'element-plus/dist/index.css'

import App from './App.vue'
import { installElementPlus } from './plugins/element'
import router from './router'
import './styles/main.css'

const app = createApp(App)
app.use(createPinia()).use(router)
installElementPlus(app)
app.mount('#app')

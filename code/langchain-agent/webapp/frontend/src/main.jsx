// 【v2 网页版新增】前端入口：把 <App /> 组件渲染到 index.html 的 <div id="root"> 里
//
// 【在整体流程里的位置】浏览器打开页面 → 加载 index.html → 执行本文件 → 渲染 App（App 里再包含其他组件）
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import './styles.css' // 全局样式；Vite 会把它注入到页面里

// createRoot：在 #root 这个 div 上创建 React 的「画布」，render 把组件画上去
// StrictMode：开发时的额外检查（比如故意把某些函数执行两次，帮你发现副作用写错的地方），打包上线后不生效
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

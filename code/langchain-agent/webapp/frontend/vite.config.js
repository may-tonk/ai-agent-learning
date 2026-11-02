// 【v2 网页版新增】Vite 配置：开发服务器怎么启动、/api 请求转发给谁
//
// Vite 是什么：前端的「开发服务器 + 打包工具」。npm run dev 时它做两件事：
//   ① 把 src/ 里的 .jsx 实时翻译成浏览器能运行的 JS，改代码后页面自动刷新
//   ② 在 http://localhost:5173 提供页面
// 谁读它：npm run dev / npm run build 时 Vite 自动读取本文件
import { defineConfig } from 'vite'
// React 插件：让 Vite 认识 .jsx 语法（<div>…</div> 写在 JS 里），并支持改代码后不刷新整页的热更新
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // 注意（实测踩坑）：不写 host 时，Vite 在你电脑上只监听 IPv6 的 ::1（localhost 被 Node 解析成了 ::1），
    //   浏览器打开 localhost:5173 没问题，但 webapp/scripts/chat_probe.py 请求 127.0.0.1:5173 会「连接被拒绝」。
    //   明确写成 127.0.0.1：浏览器用 localhost 或 127.0.0.1 都能打开，脚本也能连上
    host: '127.0.0.1',
    port: 5173,
    // strictPort：5173 被占用时直接报错，而不是悄悄换成 5174（换了端口，后端 CORS 白名单就对不上了）
    strictPort: true,
    // 转发（代理）：页面里请求 /api/xxx 时，由 Vite 转发给 FastAPI（127.0.0.1:8001）
    // 好处：在浏览器看来，页面和接口都在 :5173，同一个地址 → 不存在跨域问题；
    //       前端代码里只写 /api/chat，不用写死后端地址，部署时换地址也不用改代码
    // 注意：写 127.0.0.1 而不是 localhost —— Node 有时把 localhost 解析成 IPv6 的 ::1，
    //       而 uvicorn 默认只监听 IPv4 的 127.0.0.1，会出现「连接被拒绝」
    proxy: {
      '/api': 'http://127.0.0.1:8001',
    },
  },
})

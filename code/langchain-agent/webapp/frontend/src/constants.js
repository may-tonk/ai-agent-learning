// 【v2 网页版新增】前端用到的「固定文字」集中放这里：工具中文名、欢迎页的示例问题、角色中文名
//
// 为什么单独一个文件（真实项目的做法）：
//   这些都是「显示用的配置」，不是逻辑。放一处，以后加工具、改文案只改这里，组件代码不用动。
// 谁用它：components/MessageBubble.jsx（工具中文名）、components/ChatWindow.jsx（示例问题）、
//         components/Sidebar.jsx（角色中文名）

// 工具英文名 → 页面上显示的中文名。
// 名字来自 agent/tools/*.py 里 @tool 函数的函数名（后端 tool_calls 里的 name 就是它）。
// 没在这里登记的新工具，页面会直接显示英文名，不会出错。
export const TOOL_LABELS = {
  search_knowledge: '检索知识库',
  list_my_orders: '查询我的订单',
  get_order_detail: '查询订单详情',
  check_warranty: '检查保修',
  create_repair_ticket: '创建报修工单',
  get_ticket_status: '查询工单进度',
  update_ticket_status: '更新工单状态',
}

// 后端 users.json 里的 role → 中文
export const ROLE_LABELS = {
  customer: '普通用户',
  supervisor: '客服主管',
}

// 欢迎页的示例问题：点一下就直接发送。
// 每条覆盖一类能力，方便演示：订单工具、知识库检索、保修判断、报修工单
export const SUGGESTIONS = [
  { title: '我的订单', text: '帮我查一下我名下有哪些订单？' },
  { title: '使用问题', text: '扫地机器人回不了充电座怎么办？' },
  { title: '保修判断', text: '我最早那个订单的电池坏了，还在保修期吗？' },
  { title: '耗材保养', text: '滤网和边刷多久需要更换一次？' },
]

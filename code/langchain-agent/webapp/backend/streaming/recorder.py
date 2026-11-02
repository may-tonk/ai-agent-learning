"""
【v2 网页版新增 · 阶段 4】把一轮对话的事件「记下来」，整理成一条可以存进消息表的客服消息

【为什么需要它】
    浏览器那边，App.jsx 的 applyEvent 收到一条条事件，把它们拼成页面上的一个气泡（文字、工具标签、参考资料、审批卡片）。
    刷新页面后，这个气泡要能原样显示回来，所以后端也要把同样的事件拼成同样的形状，存进消息表。
    本类就是 applyEvent 的 Python 版：规则一模一样，两边对照着看。

【在整体流程里的位置】
    routers/chat.py 的 _sse_response：每推给浏览器一条事件，同时交给 recorder.apply(事件名, 数据)
    → 这一轮结束（正常结束 / 出错 / 点了停止）→ 把 recorder.message 写进 messages 表
    → 刷新页面时 GET /api/threads/{id}/messages 读出来 → MessageBubble 照常显示

recorder.message 的形状（和前端 MessageBubble 的 props 一致）：
    text      最终回答
    tools     [{id, name, args, status: running / ok / error / stopped, progress: [{step, status, message}]（阶段 6，只有检索有）}]
    sources   参考资料文件名
    pending   待审批的操作（停在审批上时不为空，刷新后审批卡片还在）
    decision  {approved, reason, items}：审批卡片点过之后的记录
    stopped   是否被「停止」按钮打断
    error     出错时给用户看的提示
"""
from webapp.backend.streaming import protocol


def empty_message() -> dict:
    """一条空的客服消息（和 App.jsx send() 里放上去的那条空消息字段一样）"""
    return {"text": "", "tools": [], "sources": [], "pending": [], "decision": None, "stopped": False, "error": None}


class TurnRecorder:
    def __init__(self, message: dict | None = None):
        # message：从一条已有的消息接着记（审批后继续，见 resume()）；不传 = 新的一轮
        self.message = message or empty_message()
        self.call = 0  # 当前是第几次模型调用，规则同前端：call 变了，之前的文字作废
        self.finished = False  # 是否收到了 done 事件（没收到就离开 = 被停止或断开）

    @classmethod
    def resume(cls, message: dict, approved: bool, reason: str) -> "TurnRecorder":
        """
        审批后继续：在停在审批上的那条消息上接着记（对应 App.jsx 的 decide()）
            待审批的操作 → 变成一条「已批准 / 已拒绝」的记录；文字清空，后面的回答以这次运行为准
        """
        msg = {**empty_message(), **message}
        msg["decision"] = {"approved": approved, "reason": reason, "items": msg["pending"]}
        msg.update(pending=[], text="", error=None)
        return cls(msg)

    @classmethod
    def from_response(cls, result: dict) -> dict:
        """
        不流式的 POST /api/chat 用：没有一条条事件，只有最后的 ChatResponse（字典），直接整理成一条消息。
        工具都算「完成」（不流式时拿不到每个工具的成败），id 按顺序编号
        """
        r = cls()
        r.message["tools"] = [
            {"id": f"call_{i}", "name": t["name"], "args": t["args"], "status": "ok"} for i, t in enumerate(result["tool_calls"])
        ]
        r.apply(protocol.DONE, {"status": "interrupted" if result["pending_approvals"] else "completed", **result})
        return r.message

    def apply(self, event: str, data: dict) -> None:
        """应用一条事件（事件名和数据见 streaming/protocol.py）。每个分支对应 App.jsx applyEvent 里的同名 case"""
        m = self.message
        if event == protocol.TOKEN:
            m["text"] = m["text"] + data["text"] if data["call"] == self.call else data["text"]
            self.call = data["call"]
        elif event == protocol.TOOL_STARTED:
            m["text"] = ""
            m["tools"].append({"id": data["id"], "name": data["name"], "args": data["args"], "status": "running"})
        elif event == protocol.TOOL_FINISHED:
            for t in m["tools"]:
                if t["id"] == data["id"]:
                    t["status"] = "ok" if data["ok"] else "error"
            m["sources"] += [s for s in data["sources"] if s not in m["sources"]]
        elif event == protocol.TOOL_PROGRESS:
            # 【阶段 6】同一个步骤（step）只占一行：已有就更新（running → done），没有就追加
            for t in m["tools"]:
                if t["id"] == data["id"]:
                    progress = t.setdefault("progress", [])
                    item = {"step": data["step"], "status": data["status"], "message": data["message"]}
                    i = next((k for k, p in enumerate(progress) if p["step"] == data["step"]), None)
                    if i is None:
                        progress.append(item)
                    else:
                        progress[i] = item
        elif event == protocol.APPROVAL_REQUIRED:
            m["pending"] = data["pending"]
        elif event == protocol.ERROR:
            m["error"] = data["message"]
        elif event == protocol.DONE:
            self.finished = True
            if data["status"] != "error":
                # 以 done 里的完整结果为准（return_direct 的工具结果只在这里有）
                m["text"], m["sources"], m["pending"] = data["answer"], data["sources"], data["pending_approvals"]

    def mark_stopped(self) -> None:
        """没收到 done 就结束了（点了停止 / 浏览器断开）：和前端一样，已有文字保留，没跑完的工具标成 stopped"""
        self.message["stopped"] = True
        for t in self.message["tools"]:
            if t["status"] == "running":
                t["status"] = "stopped"

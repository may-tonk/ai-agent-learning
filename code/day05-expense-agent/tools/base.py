from pydantic import BaseModel, ConfigDict


class ToolArgs(BaseModel):
    """所有工具参数模型的基类。extra="forbid"：模型多传了没定义的字段就报错，
    生成 JSON Schema 时对应 "additionalProperties": false。"""
    model_config = ConfigDict(extra="forbid")

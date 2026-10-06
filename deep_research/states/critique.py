#***********************************************
#      Filename: critique.py
#   Description: 批评Agent的格式化输出  
#***********************************************

from pydantic import BaseModel


class Critique(BaseModel):
    """一次性修稿批评；完成修稿后从待处理队列移除，不追踪解决状态。"""

    # 用于追踪生成批评的Agent（例如，"Red Team", "Safety Filter"），以便于问责。
    author: str

    # 在报告草稿中发现的具体逻辑谬误、偏见或事实错误。
    concern: str

# 信息返回格式规范

class MsgReturn():
    def __init__(self,content,type,gorType,extra,default_response):
        """
        参数说明
        content:返回文本
        type:原返回中default_response的type
        gorType:实际系统使用的type，会单独赋值并绑定相应逻辑，目前分为六种（think,answer,tool,end,error,connection_error）
        extra:额外包体dict
        default_response:原本的返回内容，用于防止现体系无法兼容一些特殊情况的backup，非必要不使用
        """
        self.content=content  
        self.type=type
        self.gorType=gorType
        self.extra=extra
        self.default_response=default_response

    def get_response(self):
        """
        获取default_response方法
        """
        return self.default_response

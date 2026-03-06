from ._model_base import model_base
from ._openai_model import openai_chat_completetion_model
from ._anthropic_model import anthropic_model
from ._openai_response_model import openai_response_model
from ._openai_chat_interleaved_model import openai_chat_interleaved_model
from ._anthropic_interleaved_model import anthropic_interleaved_model

__all__ = [
    "model_base",
    "openai_chat_completetion_model",
    "anthropic_model",
    "openai_response_model",
    "openai_chat_interleaved_model",
    "anthropic_interleaved_model",
    "create_model"
]

def create_model(base_url, api_key, model_name, stream=True, extra_args=None, router="openai-chat"):
    """
    根据router参数创建对应的模型实例

    Args:
        base_url: API基础URL
        api_key: API密钥
        model_name: 模型名称
        stream: 是否使用流式输出
        extra_args: 额外参数
        router: 路由类型，决定使用哪种模型实现

    Returns:
        模型实例
    """
    if router == "openai-chat":
        return openai_chat_completetion_model(
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            stream=stream,
            extra_args=extra_args,
            router=router
        )
    elif router == "anthropic":
        return anthropic_model(
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            stream=stream,
            extra_args=extra_args,
            router=router
        )
    elif router == "openai-chat-interleaved":
        return openai_chat_interleaved_model(
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            stream=stream,
            extra_args=extra_args,
            router=router
        )
    elif router == "anthropic-interleaved":
        return anthropic_interleaved_model(
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            stream=stream,
            extra_args=extra_args,
            router=router
        )
    elif router == "openai-response":
        return openai_response_model(
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            stream=stream,
            extra_args=extra_args,
            router=router
        )

    else:
        raise ValueError(f"Unsupported router type: {router}")
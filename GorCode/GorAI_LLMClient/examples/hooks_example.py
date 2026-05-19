from GorAI_LLMClient import HookEvent, HookResult, create_model


def replace_before_request(context):
    if context.loop_round != 0:
        return None
    messages = list(context.messages)
    messages.append({
        "role": "system",
        "content": "This message was inserted by a lifecycle hook.",
    })
    return HookResult(messages=messages)


model = create_model(
    base_url="https://example.invalid/v1",
    api_key="your-api-key",
    model_name="your-model",
    router="openai-chat",
)
model.add_hook(HookEvent.BEFORE_MODEL_REQUEST.value, replace_before_request)

"""由旧虚拟环境单独启动的离线模型进程，不依赖新环境中的SciPy。

stdin接收消息及本机模型路径；stdout只返回JSON。模型权重只读，不训练、
不加载LoRA、不访问网络。外层父进程负责硬超时，generate还带软时间限制。
"""
import json
import os
import sys
import time

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"


def main():
    request = json.load(sys.stdin)
    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer
    start = time.perf_counter()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable. This local configuration requires the existing GPU environment.")
    torch.manual_seed(0)
    tokenizer = AutoTokenizer.from_pretrained(request["model_path"], local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(request["model_path"], local_files_only=True,
                                               dtype=torch.float16).to("cuda").eval()
    text = tokenizer.apply_chat_template(request["messages"], tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt").to("cuda")
    if inputs["input_ids"].shape[1] > 7000:
        raise ValueError("Prompt exceeds this demo's 7000-token budget.")
    loaded = time.perf_counter()
    with torch.inference_mode():
        outputs = model.generate(**inputs, max_new_tokens=request["max_new_tokens"],
                                 do_sample=False, max_time=request["generation_seconds"],
                                 pad_token_id=tokenizer.eos_token_id)
    new_tokens = outputs[0, inputs["input_ids"].shape[1]:]
    reply = tokenizer.decode(new_tokens, skip_special_tokens=True)
    eos = model.generation_config.eos_token_id
    eos_ids = eos if isinstance(eos, list) else [eos]
    print(json.dumps({
        "raw_text": reply, "model": "Qwen/Qwen2.5-0.5B-Instruct", "revision": os.path.basename(request["model_path"]),
        "torch": torch.__version__, "transformers": transformers.__version__,
        "load_seconds": round(loaded-start, 3), "generation_seconds": round(time.perf_counter()-loaded, 3),
        "generated_tokens": len(new_tokens), "finished_with_eos": int(new_tokens[-1]) in eos_ids,
        "peak_gpu_mib": round(torch.cuda.max_memory_allocated()/1024**2),
    }, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    main()

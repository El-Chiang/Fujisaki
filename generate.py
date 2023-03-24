from dis import Instruction
import sys
import torch
from peft import PeftModel
import transformers
import gradio as gr
import json

assert (
    "LlamaTokenizer" in transformers._import_structure["models.llama"]
), "LLaMA is now in HuggingFace's main branch.\nPlease reinstall it: pip uninstall transformers && pip install git+https://github.com/huggingface/transformers.git"
from transformers import LlamaTokenizer, LlamaForCausalLM, GenerationConfig

tokenizer = LlamaTokenizer.from_pretrained("decapoda-research/llama-7b-hf")

LOAD_8BIT = False
BASE_MODEL = "./luotuo_ckpt"
LORA_WEIGHTS = sys.argv[1]

if torch.cuda.is_available():
    device = "cuda"
else:
    device = "cpu"

try:
    if torch.backends.mps.is_available():
        device = "mps"
except:
    pass

if device == "cuda":
    model = LlamaForCausalLM.from_pretrained(
        BASE_MODEL,
        load_in_8bit=LOAD_8BIT,
        torch_dtype=torch.float16,
        device_map="auto",
    )
    model = PeftModel.from_pretrained(
       model,
        LORA_WEIGHTS,
        torch_dtype=torch.float16,
    )
elif device == "mps":
    model = LlamaForCausalLM.from_pretrained(
        BASE_MODEL,
        device_map={"": device},
        torch_dtype=torch.float16,
    )
    model = PeftModel.from_pretrained(
        model,
        LORA_WEIGHTS,
        device_map={"": device},
        torch_dtype=torch.float16,
    )
else:
    model = LlamaForCausalLM.from_pretrained(
        BASE_MODEL, device_map={"": device}, low_cpu_mem_usage=True
    )
    model = PeftModel.from_pretrained(
        model,
        LORA_WEIGHTS,
        device_map={"": device},
    )


def generate_prompt_RLHF(instruction, input=None):
    if input:
        return f"""Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
{instruction}

### Input:
{input}

### Response:"""
    else:
        return f"""Below is an instruction that describes a task. Write a response that appropriately completes the request.

### Instruction:
User: {instruction}

### Response:"""

def generate_prompt(instruction=None, input=None):
    # for now it's dummy, as we do not need instructions
    return f"[SINGLE TWEET]"

if not LOAD_8BIT:
    model.half()  # seems to fix bugs for some users.

model.eval()
if torch.__version__ >= "2" and sys.platform != "win32":
    model = torch.compile(model)


def evaluate(
    instruction=None,
    input=None,
    temperature=0.5,
    top_p=0.95,
    top_k=150,
    num_beams=1,
    max_new_tokens=224,
    **kwargs,
):
    prompt = generate_prompt_RLHF(instruction, input)
    inputs = tokenizer(prompt, return_tensors="pt")
    input_ids = inputs["input_ids"].to(device)
    generation_config = GenerationConfig(
        temperature=temperature,
        top_p=top_p,
        #top_k=top_k,
        repetition_penalty=1.1,
        length_penalty=0.1,
        num_beams=num_beams,
        do_sample=True,
        **kwargs,
    )
    with torch.no_grad():
        generation_output = model.generate(
            input_ids=input_ids,
            generation_config=generation_config,
            return_dict_in_generate=True,
            output_scores=True,
            max_new_tokens=max_new_tokens,
        )
    s = generation_output.sequences[0]
    output = tokenizer.decode(s)
    return output.split("### Response:")[1].strip()

def gradio_inference():
    gr.Interface(
    fn=evaluate,
    inputs=[
        gr.components.Textbox(
            lines=2, label="Instruction", placeholder="Tell me about alpacas."
        ),
        gr.components.Textbox(lines=2, label="Input", placeholder="none"),
        gr.components.Slider(minimum=0, maximum=1, value=0.1, label="Temperature"),
        gr.components.Slider(minimum=0, maximum=1, value=0.75, label="Top p"),
        gr.components.Slider(minimum=0, maximum=100, step=1, value=40, label="Top k"),
        gr.components.Slider(minimum=1, maximum=4, step=1, value=4, label="Beams"),
        gr.components.Slider(
            minimum=1, maximum=2000, step=1, value=128, label="Max tokens"
        ),
    ],
    outputs=[
        gr.inputs.Textbox(
            lines=5,
            label="Output",
        )
    ],
    title="🦙🌲 Alpaca-LoRA",
    description="Alpaca-LoRA is a 7B-parameter LLaMA model finetuned to follow instructions. It is trained on the [Stanford Alpaca](https://github.com/tatsu-lab/stanford_alpaca) dataset and makes use of the Huggingface LLaMA implementation. For more information, please visit [the project's website](https://github.com/tloen/alpaca-lora).",
).launch()


if __name__ == "__main__":
    print("[Enter] to generate a original tweet, [Q] and [Enter] to generate quote, [R] and [Enter] to generate a reply, Ctrl+C to exit.")
    reply_indication = "reply to other user"
    quote_indication = "quote of other's tweet"
    retweet_indication = "retweet of other's tweet"

    lang = sys.argv[2] if len(sys.argv) > 2 else "en"

    with open("prompt_i18n.json", "r") as p:
        prompt_i18n = json.load(p)
                
    prompt = prompt_i18n[lang]

    while True:
        p = input()
        if p == "q" or p == "Q":
            instruction = f"System: sample a {quote_indication} from the user's history."
            user_input = f"User: {prompt['quote']}"
        elif p == "r" or p == "R":
            instruction = f"System: sample a {reply_indication} from the user's history."
            user_input = f"User: {prompt['reply']}"
        else:
            instruction = "System: sample an original tweet from the user's history."
            user_input = f"User: {prompt['original_post']}"

        # input is still None at this moment, as we are not supporting interaction
        print("Chihiro:", evaluate(instruction, user_input))
        


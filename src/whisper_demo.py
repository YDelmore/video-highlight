import torch
from transformers import WhisperProcessor, WhisperForConditionalGeneration
import time
import os

# 1. 配置路径（根据你的项目结构调整）
# 获取当前脚本所在目录（假设脚本在 src/ 下）
current_dir = os.path.dirname(os.path.abspath(__file__))
# 模型路径：当前目录的上一级目录（项目根目录）下的 model/whisper-small
model_path = os.path.join(os.path.dirname(current_dir), "model", "whisper-small")

# 音频文件路径（你可以改成绝对路径或相对于项目根目录的路径）
audio_path = os.path.join(os.path.dirname(current_dir), "audio", "output.mp3")

# 如果你把脚本放在项目根目录运行，也可以用更简单的写法：
# model_path = "./model/whisper-small"
# audio_path = "./audio/test.mp3"

print(f"模型路径: {model_path}")
print(f"音频路径: {audio_path}")

# 2. 检查GPU是否可用
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"正在使用设备: {device.upper()}")

# 3. 加载模型和处理器
print("正在加载模型，请稍候...")
processor = WhisperProcessor.from_pretrained(model_path)
model = WhisperForConditionalGeneration.from_pretrained(model_path).to(device)

# 4. 如果使用GPU，开启半精度加速
if device == "cuda":
    model.half()
    print("已启用半精度模式 (FP16)")

# 5. 加载并处理音频
try:
    import librosa
    print(f"正在读取音频文件: {audio_path}")
    audio_input, sample_rate = librosa.load(audio_path, sr=16000)
    print(f"音频时长: {len(audio_input)/16000:.2f} 秒")
except ImportError:
    print("错误：未安装 librosa，请运行: uv pip install librosa")
    exit(1)
except FileNotFoundError:
    print(f"错误：找不到音频文件 {audio_path}")
    print("请确认文件路径是否正确，或使用绝对路径")
    exit(1)

# 6. 进行识别
print("正在识别...")
start_time = time.time()

input_features = processor(
    audio_input,
    sampling_rate=16000,
    return_tensors="pt"
).input_features.to(device)

if device == "cuda":
    input_features = input_features.half()

# 中文语音可以指定语言提升准确率
predicted_ids = model.generate(
    input_features,
    language="chinese",      # 如果是中文语音，指定为 "chinese"
    task="transcribe"        # 转录任务
    # 如果音频是英文，可以去掉 language 参数或设为 "english"
)

transcription = processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]

end_time = time.time()
print(f"\n✅ 识别完成！耗时: {end_time - start_time:.2f} 秒")
print(f"\n📝 识别结果:\n{transcription}")
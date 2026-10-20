import os
import sys
import subprocess
import json
import asyncio
from groq import Groq
import edge_tts

# UTF-8 encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def process_video_ai(video_path, output_dir, config):
    """
    Takes an input video, extracts audio, transcribes & translates via Groq,
    generates a neural English voiceover via Edge-TTS, and merges it back.
    Returns: (output_video_path, viral_caption, summary)
    """
    groq_cfg = config.get("groq", {})
    groq_api_key = groq_cfg.get("api_key")
    voice_name = groq_cfg.get("tts_voice", "en-US-ChristopherNeural")
    llm_model = groq_cfg.get("llm_model", "openai/gpt-oss-120b")
    
    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(video_path))[0]
    
    extracted_audio = os.path.join(output_dir, f"{base_name}_audio.mp3")
    dubbed_audio = os.path.join(output_dir, f"{base_name}_dubbed.mp3")
    final_video = os.path.join(output_dir, f"{base_name}_dubbed_final.mp4")

    print(f"[*] Step 1: Extracting audio from {os.path.basename(video_path)}...")
    cmd_extract = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "libmp3lame", "-ar", "44100", "-ac", "2", "-ab", "128k",
        extracted_audio
    ]
    subprocess.run(cmd_extract, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print("[*] Step 2: Transcribing & Translating with Groq Whisper...")
    client = Groq(api_key=groq_api_key)

    with open(extracted_audio, "rb") as f:
        transcription = client.audio.transcriptions.create(
            file=(os.path.basename(extracted_audio), f.read()),
            model="whisper-large-v3",
            response_format="verbose_json"
        )

    detected_lang = getattr(transcription, "language", "unknown")
    orig_text = getattr(transcription, "text", "")
    duration = getattr(transcription, "duration", 0)

    print(f"    - Detected Language: {detected_lang}")
    print(f"    - Duration: {duration:.1f}s")
    print(f"    - Original: {orig_text}")

    with open(extracted_audio, "rb") as f:
        translation = client.audio.translations.create(
            file=(os.path.basename(extracted_audio), f.read()),
            model="whisper-large-v3"
        )
    english_raw = translation.text
    print(f"    - English Translation: {english_raw}")

    print("[*] Step 3: Polishing Dub Script & Crafting Viral Caption via Groq...")
    prompt = f"""You are an expert social media and tech gadget video producer.
Video Duration: {duration:.1f} seconds.
Original text ({detected_lang}): "{orig_text}"
English translation: "{english_raw}"

Please generate strict JSON:
1. "dub_script": A fluent, natural, enthusiastic spoken English voiceover for this gadget video. Keep it conversational and timed for ~{int(duration)+1} seconds.
2. "viral_caption": A high-converting Instagram Reel / Facebook caption with a curiosity hook, problem-solution description, clear CTA, and 12-15 trending hashtags (#gadgets #technology #homefinds #gadgetsmankind etc.).
3. "summary": 1-sentence product summary.

Respond ONLY with valid JSON:
{{
  "dub_script": "...",
  "viral_caption": "...",
  "summary": "..."
}}
"""

    completion = client.chat.completions.create(
        model=llm_model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )

    ai_data = json.loads(completion.choices[0].message.content)
    dub_script = ai_data.get("dub_script", english_raw)
    viral_caption = ai_data.get("viral_caption", "")
    summary = ai_data.get("summary", "")

    print(f"    - Summary: {summary}")
    print(f"    - Polished Script: {dub_script}")

    print(f"[*] Step 4: Generating Neural Voiceover ({voice_name})...")
    async def _make_voice():
        comm = edge_tts.Communicate(dub_script, voice_name, rate="+5%")
        await comm.save(dubbed_audio)

    asyncio.run(_make_voice())

    print("[*] Step 5: Muxing audio into video & removing duplicate metadata...")
    cmd_merge = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", dubbed_audio,
        "-c:v", "copy",
        "-c:a", "aac",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        final_video
    ]
    subprocess.run(cmd_merge, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[+] Dubbed Video Ready: {final_video} ({os.path.getsize(final_video)/(1024*1024):.2f} MB)")

    return {
        "final_video": final_video,
        "caption": viral_caption,
        "summary": summary,
        "original_text": orig_text,
        "dub_script": dub_script,
        "duration": duration
    }

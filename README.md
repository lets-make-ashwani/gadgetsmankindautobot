# 🚀 Gadgets Mankind Automation Pipeline

An end-to-end, 100% automated content pipeline that:
1. Scans the Telegram bulk video channel (`@allterapost`) in **chronological order** (oldest video to newest video).
2. Downloads the video and extracts the audio.
3. Transcribes & translates Hindi voice to English using **Groq Whisper Large v3**.
4. Generates a natural, spoken English voiceover dub script and viral social media captions using **Groq LLaMA/GPT-OSS 120B**.
5. Synthesizes human-like neural English audio via **Edge-TTS** (`en-US-ChristopherNeural`).
6. Cleans duplicate metadata and muxes the new English audio into the video using **FFmpeg**.
7. Publishes the video as an **Instagram Reel** (`@gadgetsmankind`) and **Facebook Page Video** (`Gadgets mankind`) using Meta's official Graph API with **permanent tokens**.
8. Automatically tracks processed message IDs in `tracker.json` so no video is ever repeated.

---

## 📁 Directory Structure
* `config.json`: Configuration for Telegram, Groq, Meta Page, and Instagram IDs.
* `tracker.json`: Records the last processed Telegram message ID.
* `ai_dubber.py`: AI voice extraction, Whisper translation, Edge-TTS dubbing, and FFmpeg muxing.
* `publisher.py`: Resumable Instagram Reel and Facebook Page video uploaders.
* `telegram_extractor.py`: Fetches and downloads bulk videos from Telegram in oldest-to-newest order.
* `pipeline.py`: Master orchestrator with continuous interval loop or single-run modes.
* `Login_Telegram.bat`: One-time setup to log in to Telegram.
* `Process_Next_Video_Now.bat`: 1-Click launcher to process and publish 1 video immediately.
* `Start_Continuous_Automation.bat`: 1-Click launcher to run the 24/7 continuous automation (every 3 hours).

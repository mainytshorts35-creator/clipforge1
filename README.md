# ClipForge Studio — free Viewmax-inspired Shorts workflow

A Streamlit project for a personal, free-first workflow: source video → expressive AI narration presets → timed captions → vertical MP4 export.

## Run locally (Windows)

1. Install Python 3.10 or newer.
2. Install FFmpeg and ensure `ffmpeg` is on PATH.
3. Open a terminal in this folder and run:

   ```bash
   py -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   streamlit run app.py
   ```

## Deploy to GitHub + Streamlit Community Cloud

1. Upload all files in this folder to the root of your GitHub repository.
2. In Streamlit Community Cloud, choose that repository and set the main file to `app.py`.
3. Keep `packages.txt` and `requirements.txt` at the repository root.

## Notes

- Edge TTS does not need an OpenAI or ElevenLabs API key, but it does need internet access. Voice availability can change; rate and pitch controls tune delivery but cannot guarantee human-level emotion.
- Faster-Whisper downloads a model the first time captions are generated. The `base` model is configured for CPU.
- Caption masking covers the bottom region; it cannot reconstruct the image behind existing burned-in captions.
- YouTube URL downloading can fail for age-restricted, private, region-blocked, or otherwise unavailable videos. Respect copyright and platform terms.
- Long videos can exceed free hosting memory or execution limits. Trim clips before rendering.

## Voice presets

The voice panel includes casual storyteller, viral facts, sports/hype, documentary, bright conversational, playful commentary, clear explainer, and British storyteller presets. These use provider voices and rate/pitch settings; they do not clone a real creator. Only use voice cloning when you have the voice owner's permission and the model license allows your intended use.

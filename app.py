import os
import re
import streamlit as st
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled
from google import genai

GEMINI_BASE_URL = os.environ.get("AI_INTEGRATIONS_GEMINI_BASE_URL")
GEMINI_API_KEY = (
    os.environ.get("AI_INTEGRATIONS_GEMINI_API_KEY")
    or os.environ.get("GEMINI_API_KEY")
    or st.secrets.get("GEMINI_API_KEY", None)
)

if not GEMINI_API_KEY:
    st.error(
        "Gemini API key not found. "
        "Set GEMINI_API_KEY in your Streamlit Cloud secrets or environment variables."
    )
    st.stop()

if GEMINI_BASE_URL:
    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options={"base_url": GEMINI_BASE_URL, "api_version": ""},
    )
    MODEL = "gemini-2.5-flash"
else:
    client = genai.Client(api_key=GEMINI_API_KEY)
    MODEL = "gemini-1.5-flash"


def extract_video_id(url: str) -> str | None:
    patterns = [
        r"(?:v=|youtu\.be/|embed/|shorts/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def format_timestamp(seconds: float) -> str:
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def fetch_transcript(video_id: str) -> list[dict]:
    api = YouTubeTranscriptApi()
    transcript = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
    return [{"start": entry.start, "text": entry.text} for entry in transcript]


def group_transcript_by_interval(transcript: list[dict], interval_seconds: int = 60) -> list[dict]:
    groups = []
    current_group_start = None
    current_text_parts = []
    current_bucket = 0

    for entry in transcript:
        start = entry["start"]
        text = entry["text"].strip()
        bucket = int(start // interval_seconds)

        if current_group_start is None:
            current_group_start = start
            current_bucket = bucket

        if bucket != current_bucket:
            if current_text_parts:
                groups.append({
                    "timestamp": current_group_start,
                    "text": " ".join(current_text_parts),
                })
            current_group_start = start
            current_text_parts = [text]
            current_bucket = bucket
        else:
            current_text_parts.append(text)

    if current_text_parts:
        groups.append({
            "timestamp": current_group_start,
            "text": " ".join(current_text_parts),
        })

    return groups


def translate_chunk_to_burmese(timestamp_label: str, english_text: str) -> str:
    prompt = f"""You are a professional Burmese storyteller translating a movie recap.
Your task is to translate the following English transcript segment into Burmese.

Requirements:
- Use a vivid, engaging storytelling tone suitable for a movie recap (think of a narrator drawing the audience in)
- Keep the translation natural and fluid in Burmese
- Preserve the meaning faithfully
- Do NOT include any English text in your output, only Burmese
- Do NOT add any explanations or notes — just the Burmese translation

Timestamp: {timestamp_label}
English segment:
{english_text}

Burmese translation:"""

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config={"max_output_tokens": 8192},
    )
    return response.text.strip()


st.set_page_config(
    page_title="YouTube → Burmese Recap",
    page_icon="🎬",
    layout="centered",
)

st.title("🎬 YouTube to Burmese Movie Recap")
st.markdown(
    "Paste a YouTube video link below. The app will fetch its English transcript "
    "and translate it into Burmese with a cinematic storytelling style."
)

st.divider()

youtube_url = st.text_input(
    "YouTube Video URL",
    placeholder="https://www.youtube.com/watch?v=...",
)

interval_seconds = st.slider(
    "Group transcript every (seconds)",
    min_value=30,
    max_value=180,
    value=60,
    step=15,
    help="Segments of this length will each be translated as one storytelling block.",
)

translate_btn = st.button("Fetch & Translate", type="primary", use_container_width=True)

if translate_btn:
    if not youtube_url.strip():
        st.warning("Please enter a YouTube URL.")
        st.stop()

    video_id = extract_video_id(youtube_url.strip())
    if not video_id:
        st.error("Could not extract a video ID from the URL. Please check the link and try again.")
        st.stop()

    with st.spinner("Fetching English transcript..."):
        try:
            transcript = fetch_transcript(video_id)
        except NoTranscriptFound:
            st.error("No English transcript was found for this video. The video may not have English captions.")
            st.stop()
        except TranscriptsDisabled:
            st.error("Transcripts are disabled for this video.")
            st.stop()
        except Exception as e:
            st.error(f"Failed to fetch transcript: {e}")
            st.stop()

    st.success(f"Transcript fetched — {len(transcript)} entries found. Grouping into {interval_seconds}-second blocks...")

    groups = group_transcript_by_interval(transcript, interval_seconds)
    total = len(groups)
    st.info(f"Translating {total} segment(s) into Burmese. This may take a moment...")

    st.divider()
    st.subheader("📖 Burmese Movie Recap")

    progress_bar = st.progress(0, text="Starting translation...")

    results = []
    for i, group in enumerate(groups):
        ts_label = format_timestamp(group["timestamp"])
        with st.spinner(f"Translating segment {i + 1}/{total} [{ts_label}]..."):
            burmese_text = translate_chunk_to_burmese(ts_label, group["text"])

        results.append({"timestamp": ts_label, "burmese": burmese_text})
        progress_bar.progress((i + 1) / total, text=f"Translated {i + 1}/{total} segments")

        with st.container():
            st.markdown(f"**⏱ {ts_label}**")
            st.markdown(burmese_text)
            st.divider()

    progress_bar.empty()

    full_recap = "\n\n".join(
        f"[{r['timestamp']}]\n{r['burmese']}" for r in results
    )
    st.download_button(
        label="⬇️ Download Full Burmese Recap (.txt)",
        data=full_recap,
        file_name=f"burmese_recap_{video_id}.txt",
        mime="text/plain",
        use_container_width=True,
    )

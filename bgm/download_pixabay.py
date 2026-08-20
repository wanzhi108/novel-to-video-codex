"""
从 Pixabay 下载免版税 BGM 配乐，替换 ffmpeg 和弦合成
格式: https://pixabay.com/music/download/music-{ID}.mp3
"""
import urllib.request, os, time
from pathlib import Path

BGM_DIR = Path(__file__).parent

# 8种情绪 → Pixabay 音乐 ID 映射（精选高质量免版税配乐）
MOOD_TRACKS = {
    "action":   ("Action_Epic.mp3",     "https://pixabay.com/music/download/music-513668.mp3"),
    "epic":     ("Epic_Cinematic.mp3",  "https://pixabay.com/music/download/music-482367.mp3"),
    "horror":   ("Horror_Scary.mp3",    "https://pixabay.com/music/download/music-509948.mp3"),
    "mysterious":("Mysterious.mp3",     "https://pixabay.com/music/download/music-380684.mp3"),
    "sad":      ("Sad_Emotional.mp3",   "https://pixabay.com/music/download/music-509537.mp3"),
    "tense":    ("Tense_Suspense.mp3",  "https://pixabay.com/music/download/music-375422.mp3"),
    "warm":     ("Warm_Happy.mp3",      "https://pixabay.com/music/download/music-513173.mp3"),
    "happy":    ("Happy_Upbeat.mp3",    "https://pixabay.com/music/download/music-114950.mp3"),
}

def download_with_retry(url, path, max_retries=3):
    """带重试的下载"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                if len(data) > 10000:  # 至少10KB才认为有效
                    Path(path).write_bytes(data)
                    size_kb = len(data) / 1024
                    return True, size_kb
                else:
                    print(f"  ⚠ 重试 {attempt+1}: 文件太小 ({len(data)}B)")
        except Exception as e:
            print(f"  ⚠ 重试 {attempt+1}: {e}")
        time.sleep(2)
    return False, 0

def main():
    success_count = 0
    total = len(MOOD_TRACKS)
    
    for mood, (filename, url) in MOOD_TRACKS.items():
        out_path = BGM_DIR / filename
        print(f"\n[{mood}] {filename}")
        print(f"  URL: {url}")
        
        ok, size_kb = download_with_retry(url, str(out_path))
        if ok:
            print(f"  ✅ 成功: {size_kb:.0f}KB")
            success_count += 1
        else:
            print(f"  ❌ 失败")
    
    print(f"\n{'='*50}")
    print(f"完成: {success_count}/{total} 首")
    print(f"目录: {BGM_DIR}")
    
    # 列出所有文件
    for f in sorted(BGM_DIR.glob("*.mp3")):
        size_kb = f.stat().st_size / 1024
        print(f"  {f.name}: {size_kb:.0f}KB")

if __name__ == "__main__":
    main()

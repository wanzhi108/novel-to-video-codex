"""云端文生视频适配器 — Novel2Vid -> buddy-cloud.py 桥接层
用法: python cloud_video.py "<prompt>" "<output_path>"
Token 从环境变量 CLOUD_VIDEO_TOKEN 读取

前置条件:
  - CLOUD_VIDEO_TOKEN 在 .env 中设置
  - 有网络连接 (buddy-cloud.py 调用 copilot.tencent.com API)
  - 并发限制: 最多 2 个并发请求
"""
import sys, os, json, subprocess, urllib.request, time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

_BUDDY_CLOUD_DEFAULT = (Path(os.environ.get("LOCALAPPDATA",
    str(Path.home() / "AppData/Local"))) / "Programs/WorkBuddy/resources/app.asar.unpacked/resources/builtin-skills/buddy-multimodal-generation/scripts/buddy-cloud.py")
BUDDY_CLOUD = Path(os.environ.get("BUDDY_CLOUD_PATH", "")) or _BUDDY_CLOUD_DEFAULT


def _call_buddy(prompt: str, token: str, timeout: int = 600) -> tuple[dict, str]:
    """调用 buddy-cloud.py 并返回 (解析后的JSON, 错误信息)"""
    try:
        result = subprocess.run(
            [sys.executable, str(BUDDY_CLOUD), "video", prompt, "--token-stdin"],
            input=token,
            capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return {}, f"超时 ({timeout}s): API 无响应"
    except Exception as e:
        return {}, f"子进程异常: {e}"

    if result.returncode != 0:
        try:
            err_data = json.loads(result.stdout.strip())
            msg = err_data.get("message", err_data.get("error", f"RC={result.returncode}"))
            return err_data, msg
        except json.JSONDecodeError:
            return {}, f"RC={result.returncode}, stderr: {result.stderr[:200]}"

    try:
        data = json.loads(result.stdout.strip())
        return data, ""
    except json.JSONDecodeError:
        return {}, f"JSON 解析失败: {result.stdout[:200]}"


def generate(prompt: str, output_path: str, timeout: int = 600, max_retries: int = 5) -> bool:
    token = os.environ.get("CLOUD_VIDEO_TOKEN", "")
    if not token:
        print("[CloudT2V] ❌ CLOUD_VIDEO_TOKEN 未设置", flush=True)
        return False

    if not BUDDY_CLOUD.exists():
        print(f"[CloudT2V] ❌ buddy-cloud.py 未找到", flush=True)
        return False

    print(f"[CloudT2V] 生成: {prompt[:80]}...", flush=True)

    # 重试循环（处理并发限制 429）
    for attempt in range(max_retries):
        data, err = _call_buddy(prompt, token, timeout)

        if data.get("status") == "DONE":
            break  # 成功

        http_status = data.get("http_status", 0)

        if http_status == 429:
            wait = min((attempt + 1) * 15, 60)
            print(f"[CloudT2V] ⚠️ 并发槽位满 (429)，{wait}s 后重试 ({attempt+1}/{max_retries})...", flush=True)
            time.sleep(wait)
            continue

        if "TOKEN" in err.upper() or "AUTH" in err.upper():
            print(f"[CloudT2V] ❌ 认证失败: {err[:150]}", flush=True)
            return False

        if http_status >= 500:
            wait = min((attempt + 1) * 10, 30)
            print(f"[CloudT2V] ⚠️ 服务器错误 ({http_status})，{wait}s 后重试...", flush=True)
            time.sleep(wait)
            continue

        print(f"[CloudT2V] ❌ {err[:200]}", flush=True)
        return False

    if data.get("status") != "DONE":
        print(f"[CloudT2V] ❌ 重试{max_retries}次后仍失败: {err[:200]}", flush=True)
        return False

    url = data.get("result_url", "")
    if isinstance(url, list):
        url = url[0] if url else ""

    if not url:
        print(f"[CloudT2V] ❌ 无结果 URL", flush=True)
        return False

    try:
        urllib.request.urlretrieve(url, output_path)
    except Exception as e:
        print(f"[CloudT2V] ❌ 下载失败: {e}", flush=True)
        return False

    if Path(output_path).exists() and Path(output_path).stat().st_size > 10000:
        print(f"[CloudT2V] ✅ 完成 {Path(output_path).stat().st_size/1024:.0f}KB", flush=True)
        return True
    return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python cloud_video.py <prompt> <output_path>", file=sys.stderr)
        sys.exit(1)
    ok = generate(sys.argv[1], sys.argv[2])
    sys.exit(0 if ok else 1)

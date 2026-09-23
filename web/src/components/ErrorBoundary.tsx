import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
  hasError: boolean;
}

/**
 * 全局错误边界：任何渲染异常都显示可读错误，而不是整页白屏。
 * 提供"刷新 / 回首页 / 重试"按钮便于恢复。
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, hasError: false };

  static getDerivedStateFromError(error: Error): State {
    return { error, hasError: true };
  }

  componentDidCatch(error: Error, info: unknown) {
    // 也输出到控制台便于排查
    console.error("[ErrorBoundary] 渲染异常:", error, info);
  }

  handleReload = () => {
    window.location.reload();
  };

  handleGoHome = () => {
    window.location.href = "/";
  };

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          height: "100vh",
          background: "#09090f",
          color: "#e4e0d8",
          fontFamily: "system-ui, sans-serif",
          padding: "24px",
          textAlign: "center",
        }}
      >
        <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "12px" }}>
          ⚠️ 界面出现异常
        </div>
        <div
          style={{
            maxWidth: "680px",
            background: "#1e1e2a",
            border: "1px solid #2a2a38",
            borderRadius: "8px",
            padding: "16px",
            marginBottom: "20px",
            textAlign: "left",
            overflow: "auto",
            maxHeight: "300px",
            width: "100%",
          }}
        >
          <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: "12px", color: "#ff8f8f" }}>
            {this.state.error?.message || String(this.state.error)}
          </pre>
        </div>
        <div style={{ display: "flex", gap: "12px" }}>
          <button
            onClick={this.handleReload}
            style={{
              padding: "10px 22px",
              borderRadius: "6px",
              border: "none",
              background: "#c8a45c",
              color: "#0a0a10",
              cursor: "pointer",
              fontSize: "14px",
            }}
          >
            刷新页面
          </button>
          <button
            onClick={this.handleGoHome}
            style={{
              padding: "10px 22px",
              borderRadius: "6px",
              border: "1px solid #2a2a38",
              background: "transparent",
              color: "#e4e0d8",
              cursor: "pointer",
              fontSize: "14px",
            }}
          >
            回到首页
          </button>
        </div>
      </div>
    );
  }
}

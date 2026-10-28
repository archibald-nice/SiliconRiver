import { useState, useEffect } from "react";

const Footer = () => {
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 768);
    };

    checkMobile();
    window.addEventListener("resize", checkMobile);
    return () => window.removeEventListener("resize", checkMobile);
  }, []);

  // 如实描述实际数据管线：daily_sync.sh 每天 03:00（Asia/Shanghai）跑一轮同步（ISSUE-029）。
  // 曾经写的「开源每 1 小时 / 闭源每 6 小时」没有任何定时任务在兑现；
  // 排期在 2026-10-19 由 12:00 挪到凌晨 03:00（launchd StartCalendarInterval），文案必须跟着改。
  const tags = [
    "本网站获取信息来源：HuggingFace、OpenRouter",
    "开源 / 闭源模型：每日 03:00（北京时间）同步一次",
  ];

  return (
    <footer className="shrink-0 border-t border-border-default bg-surface-overlay py-2 transition-colors">
      {isMobile ? (
        // 移动端：显示 PC 端提示
        <div className="flex items-center justify-center px-4">
          <p className="text-xs text-text-muted">
            数据来源：Hugging Face、OpenRouter
          </p>
        </div>
      ) : (
        // 桌面端：显示原有内容
        <>
          {/* 第一行：左侧标签，右侧备案信息 */}
          <div className="flex items-center justify-between px-6">
            <div className="flex flex-wrap items-center gap-3">
              {tags.map((tag, index) => (
                <div
                  key={index}
                  className="inline-flex items-center rounded-full border-0 border-accent-base/20 bg-accent-soft px-3 py-1.5 text-xs font-medium text-accent-base"
                >
                  {tag}
                </div>
              ))}
            </div>
            <div className="text-text-muted text-sm">
              粤ICP备2025436096号-2
            </div>
          </div>
          {/* 第二行：保留给公安备案信息的位置 */}

        </>
      )}
    </footer>
  );
};

export default Footer;

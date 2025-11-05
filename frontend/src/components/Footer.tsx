const Footer = () => {
  const tags = [
    "本网站获取信息来源：HuggingFace、OpenRouter",
    "开源模型拉取频率：每 1 小时",
    "闭源模型拉取频率：每 6 小时",
  ];

  return (
    <footer className="shrink-0 border-t border-border-default bg-surface-overlay py-3 transition-colors">
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
      <div className="h-4"></div>
    </footer>
  );
};

export default Footer;

import { useState, useEffect } from "react";

type MobileFilterButtonProps = {
  isOpen: boolean;
  onToggle: (open: boolean) => void;
};

const MobileFilterButton = ({ isOpen, onToggle }: MobileFilterButtonProps) => {
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 768);
    };

    checkMobile();
    window.addEventListener("resize", checkMobile);
    return () => window.removeEventListener("resize", checkMobile);
  }, []);

  if (!isMobile) return null;

  return (
    <button
      onClick={() => onToggle(!isOpen)}
      className="fixed bottom-6 right-6 z-40 flex items-center justify-center w-14 h-14 rounded-full bg-accent-base text-white shadow-lg transition-all duration-200 hover:shadow-xl hover:scale-110 focus:outline-none focus:ring-2 focus:ring-accent-base focus:ring-offset-2"
      aria-label={isOpen ? "关闭筛选器" : "打开筛选器"}
      aria-expanded={isOpen}
    >
      <svg
        className={`w-6 h-6 transition-transform duration-300 ${isOpen ? 'rotate-90' : ''}`}
        fill="currentColor"
        viewBox="0 0 24 24"
      >
        <path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z" />
      </svg>
    </button>
  );
};

export default MobileFilterButton;

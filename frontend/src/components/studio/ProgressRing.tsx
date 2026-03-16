/**
 * ProgressRing — 环形进度条组件，显示 "Day X/N" 学习进度。
 * 纯前端 SVG 实现，数据来自 studioStore.allDays。
 */

interface ProgressRingProps {
  completed: number;
  total: number;
  size?: number;
}

export default function ProgressRing({ completed, total, size = 48 }: ProgressRingProps) {
  if (total <= 0) return null;

  const strokeWidth = 4;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const ratio = Math.min(completed / total, 1);
  const offset = circumference * (1 - ratio);
  const isComplete = completed >= total;
  const center = size / 2;

  return (
    <div
      className="inline-flex items-center gap-2"
      role="progressbar"
      aria-valuenow={completed}
      aria-valuemin={0}
      aria-valuemax={total}
      aria-label={`学习进度：${completed}/${total} 天`}
    >
      <svg width={size} height={size} className="transform -rotate-90">
        {/* 背景环 */}
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke="currentColor"
          className="text-gray-200 dark:text-gray-700"
          strokeWidth={strokeWidth}
        />
        {/* 进度环 */}
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke="currentColor"
          className={isComplete ? "text-[#D97757]" : "text-[#D97757]/60"}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 0.5s ease" }}
        />
      </svg>
      <span className="text-xs text-[#5F6368] whitespace-nowrap font-medium">
        {isComplete ? (
          <span className="text-[#D97757]">✓ 完成</span>
        ) : (
          `Day ${completed}/${total}`
        )}
      </span>
    </div>
  );
}

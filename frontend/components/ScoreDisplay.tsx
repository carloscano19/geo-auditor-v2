"use client";

interface ScoreDisplayProps {
    score: number;
    label?: string;
    size?: "sm" | "md" | "lg";
}

export default function ScoreDisplay({
    score,
    label,
    size = "lg",
}: ScoreDisplayProps) {
    // Calculate score color
    const getScoreColor = (score: number) => {
        if (score >= 80) return { stroke: "#22c55e", text: "text-score-excellent" };
        if (score >= 60) return { stroke: "#84cc16", text: "text-score-good" };
        if (score >= 40) return { stroke: "#eab308", text: "text-score-warning" };
        if (score >= 20) return { stroke: "#f97316", text: "text-score-poor" };
        return { stroke: "#ef4444", text: "text-score-critical" };
    };

    const { stroke, text } = getScoreColor(score);

    // Size configurations
    const sizeConfig = {
        sm: { size: 80, strokeWidth: 6, fontSize: "text-xl" },
        md: { size: 120, strokeWidth: 8, fontSize: "text-3xl" },
        lg: { size: 180, strokeWidth: 10, fontSize: "text-5xl" },
    };

    const config = sizeConfig[size];
    const radius = (config.size - config.strokeWidth) / 2;
    const circumference = 2 * Math.PI * radius;
    const progress = ((100 - score) / 100) * circumference;

    return (
        <div className="flex flex-col items-center gap-2">
            <div className="relative" style={{ width: config.size, height: config.size }}>
                {/* Background circle */}
                <svg
                    className="transform -rotate-90"
                    width={config.size}
                    height={config.size}
                >
                    <circle
                        cx={config.size / 2}
                        cy={config.size / 2}
                        r={radius}
                        fill="none"
                        stroke="#262626"
                        strokeWidth={config.strokeWidth}
                    />
                    {/* Progress circle */}
                    <circle
                        cx={config.size / 2}
                        cy={config.size / 2}
                        r={radius}
                        fill="none"
                        stroke={stroke}
                        strokeWidth={config.strokeWidth}
                        strokeLinecap="round"
                        strokeDasharray={circumference}
                        strokeDashoffset={progress}
                        className="score-circle transition-all duration-1000 ease-out"
                    />
                </svg>
                {/* Score text */}
                <div className="absolute inset-0 flex items-center justify-center">
                    <span className={`font-bold ${config.fontSize} ${text}`}>
                        {Math.round(score)}
                    </span>
                </div>
            </div>
            {label && (
                <span className="text-sm font-medium text-text-secondary">{label}</span>
            )}
        </div>
    );
}

"use client";

import { StatTile, type StatTileTone } from "@/components/ui/stat-tile";
import { Award } from "lucide-react";

interface ScoreDisplayProps {
    score: number;
    label?: string;
    sublabel?: string;
    size?: "sm" | "md" | "lg";
}

export default function ScoreDisplay({
    score,
    label = "Overall GEO Score",
    sublabel,
}: ScoreDisplayProps) {
    const getScoreTone = (s: number): StatTileTone => {
        if (s >= 80) return "good";
        if (s >= 60) return "good";
        if (s >= 40) return "warn";
        if (s >= 20) return "critical";
        return "critical";
    };

    const getScoreQualitative = (s: number): string => {
        if (s >= 80) return "Excellent citability";
        if (s >= 60) return "Good potential";
        if (s >= 40) return "Moderate coverage";
        if (s >= 20) return "Weak visibility";
        return "Critical issues";
    };

    const tone = getScoreTone(score);
    const rounded = Math.round(score);

    return (
        <StatTile
            hero
            tone={tone}
            icon={<Award className="size-5" />}
            figure={`${rounded}/100`}
            label={label}
            hint={sublabel || getScoreQualitative(score)}
            share={{
                current: rounded,
                total: 100,
                label: "Engine Readiness",
            }}
            className="w-full"
        />
    );
}

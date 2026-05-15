from __future__ import annotations


class ZoneMapper:
    def map_percentile(self, percentile: float, archetype: dict) -> tuple[float, str]:
        if percentile < 0:
            return (0.0, "invalid")

        zones = archetype["zones"]
        prev_max = 0.0

        for zone_name, zone_data in zones.items():
            zone_max = zone_data["percentile_max"]
            score_min, score_max = zone_data["score_range"]

            if percentile <= zone_max:
                if zone_max == prev_max:
                    return (float(score_max), zone_name)

                score = score_max - ((percentile - prev_max) / (zone_max - prev_max)) * (score_max - score_min)
                return (round(score, 2), zone_name)

            prev_max = zone_max

        return (0.0, "avoid")

def calculate_match_points(match_data: dict, team_key: str) -> dict:
    if not match_data or "score_breakdown" not in match_data or not match_data["score_breakdown"]:
        return {"total_points": 0, "breakdown": {}}

    alliance_color = None
    if team_key in match_data.get("alliances", {}).get("red", {}).get("team_keys", []):
        alliance_color = "red"
    elif team_key in match_data.get("alliances", {}).get("blue", {}).get("team_keys", []):
        alliance_color = "blue"

    if not alliance_color:
        return {"total_points": 0, "breakdown": {}}

    score_breakdown = match_data["score_breakdown"][alliance_color]
    opponent_color = "blue" if alliance_color == "red" else "red"

    total_score = match_data["alliances"][alliance_color]["score"]
    opponent_score = match_data["alliances"][opponent_color]["score"]

    auto_points = score_breakdown.get("autoPoints", 0)
    teleop_points = score_breakdown.get("teleopPoints", 0)
    endgame_points = score_breakdown.get("endgamePoints", 0)

    win_bonus = 0
    if total_score > opponent_score:
        win_bonus = 10
    elif total_score == opponent_score:
        win_bonus = 5

    fantasy_score = round((auto_points + teleop_points + endgame_points) / 3.0 + win_bonus, 2)

    return {
        "total_points": fantasy_score,
        "breakdown": {
            "auto": auto_points,
            "teleop": teleop_points,
            "endgame": endgame_points,
            "win_bonus": win_bonus
        }
    }
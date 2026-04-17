from __future__ import annotations

from pathlib import Path

from reverse_detective.ai_client import ReverseDetectiveAIClient
from reverse_detective.config import AIConfig
from reverse_detective.story_loader import load_story_catalog, build_story_premise


def build_mock_client() -> ReverseDetectiveAIClient:
    return ReverseDetectiveAIClient(
        AIConfig(
            provider="crs",
            base_url="",
            model="mock-story-cache",
            reasoning_effort="medium",
            timeout_seconds=30.0,
            disable_response_storage=True,
            use_mock_when_unconfigured=True,
            fallback_to_mock_on_error=True,
            credentials_path=Path("~/.reverse_detective/credentials.json").expanduser(),
        )
    )


def main() -> None:
    client = build_mock_client()
    try:
        stories = load_story_catalog()
        generated = 0
        for story in stories:
            for role in story.roles:
                premise = build_story_premise(story, role.id)
                client.generate_initial_scene(premise)
                generated += 1
                print(f"cached {story.id}:{role.id}")
        print(f"generated {generated} cached initial scenes")
    finally:
        client.close()


if __name__ == "__main__":
    main()

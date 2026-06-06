from .instagram import InstagramPublisher
from .linkedin import LinkedInPublisher
from .tiktok import TikTokPublisher
from .youtube import YouTubePublisher

PUBLISHERS: dict[str, type] = {
    "youtube": YouTubePublisher,
    "instagram": InstagramPublisher,
    "tiktok": TikTokPublisher,
    "linkedin": LinkedInPublisher,
}

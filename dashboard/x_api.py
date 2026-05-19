"""X (Twitter) API wrapper for posting briefing social posts.

Requires four environment variables:
  TWITTER_CONSUMER_KEY
  TWITTER_CONSUMER_SECRET
  TWITTER_ACCESS_TOKEN
  TWITTER_ACCESS_TOKEN_SECRET

These should be set as secrets in the HuggingFace Space and in GitHub Actions.
"""
import os

X_HANDLE = "SkaldPayments"
_REQUIRED = (
    "X_CONSUMER_KEY",
    "X_CONSUMER_SECRET",
    "X_ACCESS_TOKEN",
    "X_ACCESS_TOKEN_SECRET",
)


def available() -> bool:
    return all(os.environ.get(k) for k in _REQUIRED)


def post_tweet(text: str) -> tuple[bool, str]:
    """Post a tweet. Returns (success, message_or_url)."""
    try:
        import tweepy
    except ImportError:
        return False, "tweepy not installed"

    client = tweepy.Client(
        consumer_key=os.environ["X_CONSUMER_KEY"],
        consumer_secret=os.environ["X_CONSUMER_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    try:
        response = client.create_tweet(text=text)
        tweet_id = response.data["id"]
        return True, f"https://x.com/{X_HANDLE}/status/{tweet_id}"
    except Exception as e:
        return False, str(e)

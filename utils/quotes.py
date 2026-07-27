# -*- coding: utf-8 -*-


import random

QUOTES = [
    "🚀 Let's get it! Drop your links and let's boost each other! 🔥",
    "💫 Teamwork makes the dream work. Share your X links now!",
    "⚡ Rise and grind! Time to show the algorithm who's boss.",
    "🌟 Your content deserves to be seen. Let's get it out there!",
    "🔥 Support each other and grow together. Drop those links!",
    "💪 Community over competition. Let's boost each other up!",
    "🎯 Consistency is key. Keep posting, keep growing!",
    "🌍 Your voice matters. Let's amplify it together!",
    "✨ Every retweet is a vote of confidence. Let's go!",
    "🦁 Be bold. Be loud. Share your story with the world!",
    "💥 The grind never stops. Drop your links, let's roll!",
    "🎉 Engagement is everything. Let's make some noise!",
    "🏆 Winners support winners. Share your X posts now!",
    "🌈 Together we rise. Drop your links below!",
    "⚡ No cap — your content is fire. Let the world see it!",
    "🎶 Vibes only. Share those links and let's get trending!",
    "🦅 Fly high. Engage high. Drop your X links!",
    "💎 Diamond hands, diamond content. Let's go!",
    "🔑 The key to growth is community. Post your links!",
    "🌊 Make waves. Drop your X links and let's trend together!",
    "🎯 Aim for the top. Share your posts and let's boost!",
    "⭐ Stars support stars. Drop your links below!",
    "🚂 The hype train has left the station. All aboard — drop your links!",
    "🌺 Bloom where you're planted. Share your X content now!",
    "💡 Bright ideas deserve bright audiences. Share your links!",
]


def get_random_quote() -> str:
    return random.choice(QUOTES)

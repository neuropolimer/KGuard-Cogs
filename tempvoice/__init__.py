from .panel import TempVoicePanel
from .tempvoice import TempVoice


async def setup(bot):
    await bot.add_cog(TempVoice(bot))
    await bot.add_cog(TempVoicePanel(bot))

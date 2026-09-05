from .muteguard import MuteGuard


async def setup(bot):
    await bot.add_cog(MuteGuard(bot))

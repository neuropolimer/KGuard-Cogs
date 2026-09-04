from .modslash import ModSlash


async def setup(bot):
    await bot.add_cog(ModSlash(bot))

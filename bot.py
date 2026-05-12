import discord
import os
from discord.ext import commands
from dotenv import load_dotenv
import random
import aiohttp
import sqlite3
import time

pokemon_list = []
pokemon_sprites_list = {}
active_spawn = None
user_timeouts = {}

conn = sqlite3.connect("database.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    pokemon TEXT,
    shiny INTEGER,
    level INTEGER DEFAULT 1
)
""")
conn.commit()

cursor.execute("""
CREATE TABLE IF NOT EXISTS item_inventory (
    user_id INTEGER,
    item TEXT,
    price INTEGER
)
""")
conn.commit()

cursor.execute("""
CREATE TABLE IF NOT EXISTS wallet (
    user_id INTEGER,
    balance DOUBLE
)               
""")
conn.commit()

cursor.execute("""
CREATE TABLE IF NOT EXISTS shop (
    item TEXT,
    price DOUBLE
)           
""")
conn.commit()


def is_shiny():
    return random.randint(1, 4096) == 1


async def load_pokemon():
    global pokemon_list, pokemon_sprites_list
    url = "https://pokeapi.co/api/v2/pokemon?limit=1025"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            pokemon_list = [p["name"] for p in data["results"]]
            for info in data["results"]:
                # Extrai o ID da URL (ex: https://pokeapi.co/api/v2/pokemon/1/ -> ID 1)
                poke_id = info["url"].strip("/").split("/")[-1]
                # Monta direto a URL da imagem oficial da PokeAPI sem precisar de 1025 novos requests
                pokemon_sprites_list[info["name"]] = {
                    "normal": f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{poke_id}.png",
                    "shiny": f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/shiny/{poke_id}.png"
                }

            print(f"Sprites carregados. Exemplo (bulbasaur normal): {pokemon_sprites_list.get('bulbasaur')['normal']}")


def run_bot():
    load_dotenv()

    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix="$", intents=intents)

    @bot.event
    async def on_ready():

        await load_pokemon()

        print(f"Loaded {len(pokemon_list)} pokemon")
        print("Bot online")
        print(f"Logged in as {bot.user}")

    @bot.command()
    async def trade(ctx, member: discord.Member, pokemon_name: str):
        cursor.execute(
            "SELECT pokemon, shiny FROM inventory WHERE user_id=? AND pokemon LIKE ?",
            (ctx.author.id, f"%{pokemon_name.lower()}%"),
        )
        row = cursor.fetchone()
        print(row)

        if not row:
            await ctx.send("Você não tem esse Pokémon para trocar.")
            return

        pokemon_id = 0
        evolution_chain_url = ""
        evolution_text = ""
        url = f"https://pokeapi.co/api/v2/pokemon/{pokemon_name.lower()}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    await ctx.send("Pokémon não encontrado.")
                    return
                data = await resp.json()
                pokemon_id = data["id"]

        if pokemon_id > 0:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://pokeapi.co/api/v2/pokemon-species/{pokemon_id}"
                ) as resp:
                    if resp.status != 200:
                        await ctx.send("Pokémon não encontrado.")
                        return
                    data = await resp.json()
                    evolution_chain_url = data["evolution_chain"]["url"]

        if evolution_chain_url:
            async with aiohttp.ClientSession() as session:
                async with session.get(evolution_chain_url) as resp:
                    if resp.status != 200:
                        await ctx.send("Pokémon não encontrado.")
                        return
                    data = await resp.json()
                    chain = data["chain"]
                    evolutions = []
                    while chain:
                        evolutions.append(chain["species"]["name"])

                        if chain["evolves_to"]:
                            evo = chain["evolves_to"][0]

                            method = evo["evolution_details"][0]["trigger"]["name"]

                            evolution_name = evo["species"]["name"]

                            if method == "trade":
                                evolution_text += (
                                    f"{pokemon_name.capitalize()} evoluiu por troca "
                                    f"para {evolution_name.capitalize()}!\n"
                                )

                                pokemon_name = evolution_name

                            chain = evo

                        else:
                            break

        cursor.execute(
            "UPDATE inventory SET user_id=? WHERE user_id=? AND pokemon=?",
            (member.id, ctx.author.id, pokemon_name.lower()),
        )
        cursor.execute(
            "UPDATE inventory SET user_id=? WHERE user_id=? AND pokemon=?",
            (ctx.author.id, member.id, pokemon_name.lower()),
        )
        conn.commit()

        await ctx.send(evolution_text)

        await ctx.send(
            f"{ctx.author.mention} e {member.mention} trocaram seus {pokemon_name.capitalize()}s!"
        )

    @bot.command()
    async def spawn_pokemon(channel, pokemon_name=None, shiny_control=False):

        global active_spawn

        pokemon_id = random.randint(1, 1025)

        if pokemon_name:
            url = f"https://pokeapi.co/api/v2/pokemon/{pokemon_name.lower()}"
        else:
            url = f"https://pokeapi.co/api/v2/pokemon/{pokemon_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()

        name = data["name"]
        image = data["sprites"]["other"]["official-artwork"]["front_default"]

        shiny = is_shiny() if not shiny_control else shiny_control

        if shiny:
            image = data["sprites"]["other"]["official-artwork"]["front_shiny"]

        options = random.sample(pokemon_list, 4)
        options.append(name)
        random.shuffle(options)

        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

        text = ""

        for i, opt in enumerate(options):
            text += f"{emojis[i]} {opt.capitalize()}\n"

        msg = await channel.send("**A wild Pokémon is appearing...**")

        for e in emojis:
            await msg.add_reaction(e)

        await msg.edit(content=f"**A wild Pokémon appeared!**\n\n{image}\n\n{text}")

        active_spawn = {
            "message_id": msg.id,
            "pokemon": name,
            "options": options,
            "shiny": shiny,
            "caught": False,
        }
        
    @bot.command()
    async def show_pokemon(ctx, pokemon_name):
        cursor.execute(
            "SELECT pokemon, shiny, level FROM inventory WHERE user_id=? AND pokemon LIKE ?",
            (ctx.author.id, f"%{pokemon_name.lower()}%"),
        )
        
        row = cursor.fetchone()
        
        if not row:
            await ctx.send("Você não tem esse Pokémon.")
            return
        
        for p, shiny, level in [row]:
            sprite = pokemon_sprites_list[p]["shiny"] if shiny else pokemon_sprites_list[p]["normal"]
            
        message = f"{'✨ ' if shiny else ''}{p.capitalize()} (Level {level})\n{sprite}"
        await ctx.send(message)

    @bot.command()
    async def inv(ctx):
        cursor.execute(
            "SELECT pokemon, shiny, level FROM inventory WHERE user_id=?", (ctx.author.id,)
        )

        rows = cursor.fetchall()

        if not rows:
            await ctx("Você não tem Pokémon")
            return

        text = ""

        for p, shiny, level in rows:
            if shiny:
                text += f"✨ {p.capitalize()} (Level {level})\n"
            else:
                text += f"{p.capitalize()} (Level {level})\n"

        await ctx.send(f"**Seus Pokémons:**\n{text}")

    @bot.event
    async def on_reaction_add(reaction, user):
        global active_spawn

        if user.bot:
            return

        if user.id in user_timeouts and time.time() < user_timeouts[user.id]:
            return

        if not active_spawn:
            return

        if reaction.message.id != active_spawn["message_id"]:
            return

        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

        if str(reaction.emoji) not in emojis:
            return

        index = emojis.index(str(reaction.emoji))

        if active_spawn["options"][index] == active_spawn["pokemon"]:
            if active_spawn["caught"]:
                return

            active_spawn["caught"] = True

            shiny = active_spawn["shiny"]
            pokemon = active_spawn["pokemon"]

            level = random.randint(1, 100)

            cursor.execute(
                "INSERT INTO inventory VALUES (?, ?, ?, ?)",
                (user.id, pokemon, int(shiny), level),
            )
            conn.commit()

            balance = random.randrange(100, 1000)
            cursor.execute("INSERT INTO wallet VALUES (?, ?)", (user.id, balance))
            conn.commit()

            await reaction.message.channel.send(
                f"{user.mention} ganhou ${balance:.2f} por capturar {pokemon.capitalize()}!"
            )

            shiny_text = "✨ SHINY ✨ " if shiny else ""

            await reaction.message.channel.send(
                f"{user.mention} pegou {shiny_text}**{pokemon.capitalize()}**!"
            )
        else:
            user_timeouts[user.id] = time.time() + 10
            await reaction.message.channel.send(
                f"{user.mention} escolheu errado e tomou um timeout de 10 segundos para capturar!"
            )

    @bot.command()
    async def reset_inventory(ctx):
        cursor.execute("DELETE FROM inventory WHERE user_id=?", (ctx.author.id,))
        conn.commit()
        await ctx.send("Seu inventário foi resetado!")

    @bot.command()
    async def show_sprites(ctx):
        await ctx.send("Enviou a lista para o terminal")
        print(pokemon_sprites_list)

    @bot.command()
    @commands.has_role("Admin")
    async def reset_global_inventory(ctx):
        cursor.execute("DROP TABLE inventory")
        conn.commit()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER,
            pokemon TEXT,
            shiny INTEGER,
            level INTEGER DEFAULT 1
        )
        """)
        conn.commit()
        await ctx.send("Inventário global resetado!")

    @bot.command()
    async def show_wallet(ctx):
        cursor.execute("SELECT balance FROM wallet WHERE user_id=?", (ctx.author.id,))
        row = cursor.fetchone()
        if not row:
            await ctx.send("Você não tem dinheiro na carteira.")
            return
        balance = row[0]
        await ctx.send(f"**Sua carteira:** ${balance:.2f}")

    bot.run(os.getenv("DISCORD_TOKEN"))


if __name__ == "__main__":
    run_bot()

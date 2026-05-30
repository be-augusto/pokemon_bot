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

def create_pokemon_table():
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pokemon (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        normal_sprite TEXT,
        shiny_sprite TEXT,
        evolution_methods TEXT,
        evolution_items TEXT NULL
    )               
    """)
    conn.commit()

def create_inventory_table():
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

def create_item_inventory_table():
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS item_inventory (
        user_id INTEGER,
        item TEXT,
        price INTEGER,
        quantity INTEGER
    )
    """)
    conn.commit()

def create_wallet():
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS wallet (
        user_id INTEGER,
        balance DOUBLE
    )               
    """)
    conn.commit()

def create_shop():    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS shop (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item TEXT,
        price DOUBLE
    )           
    """)
    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM shop")
    if cursor.fetchone()[0] == 0:
        shop_items = [
            ("fire stone", 1000),
            ("water stone", 1000),
            ("thunder stone", 1000),
            ("leaf stone", 1000),
            ("moon stone", 1500),
            ("sun stone", 1500),
            ("shiny stone", 2000),
            ("dusk stone", 2000),
            ("dawn stone", 2000),
            ("ice stone", 2000),
            ("rare candy", 3000),
            ("king's rock", 2500),
            ("metal coat", 2500),
            ("dragon scale", 2500),
            ("up-grade", 2500),
            ("protector", 2500),
            ("electirizer", 2500),
            ("magmarizer", 2500),
            ("dubious disc", 2500),
            ("reaper cloth", 2500),
            ("prism scale", 2500)
        ]
        cursor.executemany("INSERT INTO shop (item, price) VALUES (?, ?)", shop_items)
        conn.commit()

create_shop()

def is_shiny():
    return random.randint(1, 4096) == 1


async def load_pokemon():
    global pokemon_list, pokemon_sprites_list
    url = "https://pokeapi.co/api/v2/pokemon?limit=1025"
    
    create_pokemon_table()
    
    cursor.execute("SELECT COUNT(*) FROM pokemon")
    rows = cursor.fetchone()[0]
    
    if rows == 0:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                pokemon_list = [p["name"] for p in data["results"]]
                
                # Buscar informações de evolução
                print("Baixando dados de evolução (isso pode demorar na primeira vez)...")
                evolution_map = {}
                async with session.get("https://pokeapi.co/api/v2/evolution-chain?limit=1000") as ev_resp:
                    ev_data = await ev_resp.json()
                    
                    for chain_info in ev_data["results"]:
                        # Para evitar limite de requisições, pode demorar alguns minutos. Em um projeto real, 
                        # seria recomendado usar chamadas simultâneas (gather) ou importar de um JSON fixo.
                        async with session.get(chain_info["url"]) as chain_resp:
                            if chain_resp.status != 200: continue
                            chain_detail = await chain_resp.json()
                            
                            # Função recursiva para ler a chain
                            def parse_evolution(node):
                                for evo in node["evolves_to"]:
                                    evo_name = evo["species"]["name"]
                                    details = evo["evolution_details"][0] if evo["evolution_details"] else {}
                                    
                                    trigger = details.get("trigger", {}).get("name", "unknown") if details.get("trigger") else "unknown"
                                    
                                    method = trigger
                                    item = None
                                    
                                    if trigger == "level-up":
                                        min_level = details.get("min_level")
                                        if min_level:
                                            method = f"level ({min_level})"
                                            
                                    if trigger == "use-item":
                                        item_info = details.get("item")
                                        if item_info:
                                            item = item_info.get("name").replace("-", " ")
                                            method = "item"
                                            
                                    if trigger == "trade":
                                        method = "trade"
                                        held_item = details.get("held_item")
                                        if held_item:
                                            item = held_item.get("name").replace("-", " ")

                                    # Salva como o Pokémon BASE evolui para essa evolução
                                    base_name = node["species"]["name"]
                                    
                                    if base_name not in evolution_map:
                                        evolution_map[base_name] = []
                                        
                                    evo_text = method
                                    evolution_map[base_name].append({
                                        "target": evo_name,
                                        "method": evo_text,
                                        "item": item
                                    })
                                    
                                    # Descer para a próxima evolução
                                    parse_evolution(evo)
                            
                            parse_evolution(chain_detail["chain"])

                pokemons_to_insert = []
                for info in data["results"]:
                    # Extrai o ID da URL (ex: https://pokeapi.co/api/v2/pokemon/1/ -> ID 1)
                    poke_id = info["url"].strip("/").split("/")[-1]
                    poke_name = info["name"]
                    
                    normal_url = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{poke_id}.png"
                    shiny_url = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/shiny/{poke_id}.png"
                    
                    pokemon_sprites_list[poke_name] = {
                        "normal": normal_url,
                        "shiny": shiny_url
                    }
                    
                    # Tratar os dados de evolução deste pokémon
                    evo_methods = None
                    evo_items = None
                    
                    if poke_name in evolution_map:
                        methods_list = []
                        items_list = []
                        for evo in evolution_map[poke_name]:
                            target = evo["target"]
                            method_str = f'{evo["method"]} -> {target}'
                            methods_list.append(method_str)
                            if evo["item"]:
                                item_str = f'{evo["item"]} -> {target}'
                                items_list.append(item_str)
                                
                        evo_methods = ", ".join(methods_list) if methods_list else None
                        evo_items = ", ".join(items_list) if items_list else None
                    
                    # Salva numa tupla (ordem: name, normal_sprite, shiny_sprite, evolution_methods, evolution_items)
                    pokemons_to_insert.append((poke_name, normal_url, shiny_url, evo_methods, evo_items))

                # Insere tudo de uma só vez de forma eficiente
                cursor.executemany("INSERT INTO pokemon (name, normal_sprite, shiny_sprite, evolution_methods, evolution_items) VALUES (?, ?, ?, ?, ?)", pokemons_to_insert)
                conn.commit()
    else:
        cursor.execute("SELECT name, normal_sprite, shiny_sprite FROM pokemon")
        db_pokemons = cursor.fetchall()
        for name, normal_url, shiny_url in db_pokemons:
            pokemon_list.append(name)
            pokemon_sprites_list[name] = {
                "normal": normal_url,
                "shiny": shiny_url
            }
    
    print(f"Sprites carregados")


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
    async def shop(ctx):
        cursor.execute(
            "SELECT id, item, price FROM shop"
        )
        
        rows = cursor.fetchall()
        
        if not rows:
            await ctx.send("Houve um erro ao carregar a loja")
            return
        
        message = "Bem vindo ao PokéMart!!\n\n"
        
        for id, item, price in rows:
            message += f"#{id} {item} ($: {price})\n"
            
        await ctx.send(message)

    @bot.command()
    async def inv(ctx):
        cursor.execute(
            "SELECT id, pokemon, shiny, level FROM inventory WHERE user_id=?", (ctx.author.id,)
        )

        rows = cursor.fetchall()

        if not rows:
            await ctx("Você não tem Pokémon")
            return

        text = ""

        for id, p, shiny, level in rows:
            if shiny:
                text += f"✨ #{id} {p.capitalize()} (Level {level})\n"
            else:
                text += f"#{id} {p.capitalize()} (Level {level})\n"

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
                "INSERT INTO inventory (user_id, pokemon, shiny, level) VALUES (?, ?, ?, ?)",
                (user.id, pokemon, int(shiny), level),
            )
            conn.commit()

            balance = random.randrange(100, 1000)
            
            cursor.execute("SELECT COUNT(*) FROM wallet WHERE user_id = ?", (user.id,))
            num_rows = cursor.fetchone()[0]
            
            if num_rows == 0:
                cursor.execute("INSERT INTO wallet VALUES (?, ?)", (user.id, balance))
                conn.commit()
            else:
                cursor.execute("SELECT balance FROM wallet WHERE user_id = ?", (user.id,))
                old_balance = cursor.fetchone()[0]
                new_balance = balance + old_balance
                    
                obj = (new_balance, user.id)
                cursor.execute("UPDATE wallet SET balance = ? WHERE user_id = ?", obj)
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
    async def buy_item(ctx, item_id: int, quantity: int = 1):
        import asyncio
        
        cursor.execute("SELECT item, price FROM shop WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        
        if not row:
            await ctx.send("Item não encontrado na loja.")
            return
            
        item_name, item_price = row
        total_price = item_price * quantity
        
        cursor.execute("SELECT balance FROM wallet WHERE user_id = ?", (ctx.author.id,))
        wallet_row = cursor.fetchone()
        balance = wallet_row[0] if wallet_row else 0
        
        if balance < total_price:
            await ctx.send(f"Saldo insuficiente! Custa ${total_price:.2f} e você só tem ${balance:.2f}.")
            return
            
        await ctx.send(f"Deseja comprar {quantity}x **{item_name.capitalize()}** por ${total_price:.2f}? (Digite `y` ou `yes` para confirmar, `n` ou `no` para cancelar)")
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ["y", "yes", "n", "no"]
            
        try:
            msg = await bot.wait_for('message', check=check, timeout=30.0)
        except asyncio.TimeoutError:
            await ctx.send("Tempo de resposta esgotado. Compra cancelada.")
            return
            
        if msg.content.lower() in ["n", "no"]:
            await ctx.send("Compra cancelada.")
            return
            
        # Processar a compra
        new_balance = balance - total_price
        cursor.execute("UPDATE wallet SET balance = ? WHERE user_id = ?", (new_balance, ctx.author.id))
        
        cursor.execute("SELECT quantity FROM item_inventory WHERE user_id = ? AND item = ?", (ctx.author.id, item_name))
        inv_row = cursor.fetchone()
        
        if inv_row:
            new_qty = inv_row[0] + quantity
            cursor.execute("UPDATE item_inventory SET quantity = ? WHERE user_id = ? AND item = ?", (new_qty, ctx.author.id, item_name))
        else:
            cursor.execute("INSERT INTO item_inventory (user_id, item, price, quantity) VALUES (?, ?, ?, ?)", (ctx.author.id, item_name, item_price, quantity))
            
        conn.commit()
        await ctx.send(f"Compra de {quantity}x **{item_name.capitalize()}** concluída com sucesso! Seu novo saldo é de: ${new_balance:.2f}")
        
    @bot.command()
    async def use_item(ctx, item_name: str, pokemon_id: int):
        item_name = item_name.lower().replace("-", " ")
        
        # 1. Checa se o player tem o pokemon no inventário
        cursor.execute("SELECT pokemon, shiny, level FROM inventory WHERE id = ? AND user_id = ?", (pokemon_id, ctx.author.id))
        poke_row = cursor.fetchone()
        if not poke_row:
            await ctx.send("Você não tem esse Pokémon!")
            return
            
        base_pokemon, shiny, level = poke_row
        
        # 2. Checa se o player tem o item na mochila e diminui a qtd
        cursor.execute("SELECT quantity FROM item_inventory WHERE item = ? AND user_id = ?", (item_name, ctx.author.id))
        item_row = cursor.fetchone()
        if not item_row or item_row[0] <= 0:
            await ctx.send(f"Você não tem o item **{item_name}** na mochila!")
            return
            
        qtd = item_row[0] - 1
        if qtd > 0:
            cursor.execute("UPDATE item_inventory SET quantity = ? WHERE item = ? AND user_id = ?", (qtd, item_name, ctx.author.id))
        else:
            cursor.execute("DELETE FROM item_inventory WHERE item = ? AND user_id = ?", (item_name, ctx.author.id))
            
        # 3. Pega informações nativas do pokémon (para saber se item/level dá match)
        cursor.execute("SELECT evolution_methods, evolution_items FROM pokemon WHERE name = ?", (base_pokemon,))
        evo_db = cursor.fetchone()
        
        if not evo_db:
            await ctx.send("Erro interno, infomações do banco de dados deste pokémon estão corrompidas.")
            return
            
        evo_methods = evo_db[0] or ""
        evo_items = evo_db[1] or ""
        
        # Lógica RARE CANDY (Level Up)
        if item_name == "rare candy":
            new_level = level + 1
            evolution_happened = False
            
            # Checa os métodos de level na string, ex: "level (16) -> charmeleon"
            if evo_methods:
                methods_split = evo_methods.split(", ")
                for ms in methods_split:
                    if "level" in ms:
                        # Extrai o "16" de "level (16)"
                        parts = ms.split(" -> ")
                        if len(parts) == 2:
                            lvl_str = parts[0]
                            target_pokemon = parts[1]
                            
                            lvl_num = int(lvl_str.split("(")[1].split(")")[0])
                            
                            # Se bateu ou passou o nível
                            if new_level >= lvl_num:
                                cursor.execute("UPDATE inventory SET pokemon = ?, level = ? WHERE id = ?", (target_pokemon, new_level, pokemon_id))
                                conn.commit()
                                await ctx.send(f"🍬 Você usou um Rare Candy!\nO seu **{base_pokemon.capitalize()}** subiu para o level {new_level} e evoluiu para **{target_pokemon.capitalize()}**!")
                                evolution_happened = True
                                break # só evolui para a primeira que der match (caso rare como wurmple)
            
            if not evolution_happened:
                cursor.execute("UPDATE inventory SET level = ? WHERE id = ?", (new_level, pokemon_id))
                conn.commit()
                await ctx.send(f"🍬 Você usou um Rare Candy!\nO seu **{base_pokemon.capitalize()}** subiu para o level {new_level}!")
            return
            
        # Lógica ITENS EVOLUTIVOS (Pedras, etc)
        else:
            if item_name in evo_items:
                items_split = evo_items.split(", ")
                for ev_i in items_split:
                    if item_name in ev_i:
                        # Ex: "water stone -> vaporeon"
                        target_pokemon = ev_i.split(" -> ")[1]
                        
                        cursor.execute("UPDATE inventory SET pokemon = ? WHERE id = ?", (target_pokemon, pokemon_id))
                        conn.commit()
                        await ctx.send(f"✨ A pedra emitiu um brilho ofuscante...\nO seu **{base_pokemon.capitalize()}** evoluiu para **{target_pokemon.capitalize()}**!")
                        return
                        
            # Se chegou aqui, quer dizer que ele usou a pedra num pokemon que não evolui com ela
            conn.commit() # commit da deleção do item (que a pessoa usou errado e perdeu de castigo kkkk)
            await ctx.send(f"Você tentou usar um(a) **{item_name}**, mas não teve efeito nenhum no **{base_pokemon.capitalize()}**. O item gastou!")
            return

    @bot.command()
    # @commands.has_role("Admin")
    async def reset_global_inventory(ctx):
        cursor.execute("DROP TABLE inventory")
        conn.commit()
        create_inventory_table()
        await ctx.send("Inventário global resetado!")
        
    @bot.command()
    # @commands.has_role("Admin")
    async def insert_wallet_balance(ctx):
        cursor.execute("UPDATE wallet SET balance = ? WHERE user_id = ?", (100000000, ctx.author.id))
        conn.commit()
        await ctx.send("Ficou rico")

    @bot.command()
    async def show_wallet(ctx):
        cursor.execute("SELECT balance FROM wallet WHERE user_id=?", (ctx.author.id,))
        row = cursor.fetchone()
        if not row:
            await ctx.send("Você não tem dinheiro na carteira.")
            return
        balance = row[0]
        await ctx.send(f"**Sua carteira:** ${balance:.2f}")
        
    @bot.command()
    async def show_bag(ctx):
        cursor.execute("SELECT item, quantity FROM item_inventory WHERE user_id = ?", (ctx.author.id,))
        rows = cursor.fetchall()
        
        if not rows:
            await ctx.send("Nenhum item na mochila")
        
        message = "Itens no inventário:\n"
        
        for item, quantity in rows:
            message += f"{item} {quantity}x"
            
        await ctx.send(message)
        
    @bot.command()
    async def reset_shop(ctx):
        cursor.execute("DROP TABLE SHOP")
        conn.commit()
        create_shop()
        await ctx.send("Loja Resetada!")

    @bot.command()
    async def reset_pokemon(ctx):
        cursor.execute("DROP TABLE pokemon")
        conn.commit()
        create_pokemon_table()
        await load_pokemon()
        await ctx.send("Lista de pokemons atualizada!")
        
    @bot.command()
    async def reset_item_inventory(ctx):
        cursor.execute("DROP TABLE item_inventory")
        conn.commit()
        create_item_inventory_table()
        await ctx.send("Recriada")

    bot.run(os.getenv("DISCORD_TOKEN"))


if __name__ == "__main__":
    run_bot()

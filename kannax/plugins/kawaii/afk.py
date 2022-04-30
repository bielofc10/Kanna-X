""" setup AFK mode """

import asyncio
from kannax.utils.functions import rand_array
import time
from random import choice, randint

from kannax import Config, Message, filters, get_collection, kannax
from kannax.utils import time_formatter
from kannax.plugins.utils.telegraph import upload_media_


CHANNEL = kannax.getCLogger(__name__)
SAVED_SETTINGS = get_collection("AFK_DATA")
AFK_COLLECTION = get_collection("AFK")


IS_AFK = False
IS_AFK_FILTER = filters.create(lambda _, __, ___: bool(IS_AFK))
REASON = ""
TIPO = ""
LINK = ""
TIME = 0.0
USERS = {}


async def _init() -> None:
    global IS_AFK, REASON, TIME, TIPO, LINK  # pylint: disable=global-statement
    data = await SAVED_SETTINGS.find_one({"_id": "AFK"})
    if data:
        IS_AFK = data["on"]
        REASON = data["data"]
        TIPO = data["tipo"]
        LINK = data["link"]
        TIME = data["time"] if "time" in data else 0
    async for _user in AFK_COLLECTION.find():
        USERS.update(
            {_user["_id"]: [_user["pcount"], _user["gcount"], _user["men"]]})


@kannax.on_cmd(
    "afk",
    about={
        "header": "Definir para o modo AFK",
        "description": "Define seu status como AFK. Responde a qualquer pessoa que te marcar/PM's.\n"
        "Desliga o AFK quando você digita alguma coisa.",
        "usage": "{tr}afk or {tr}afk [motivo]",
    },
    allow_channels=False,
)
async def active_afk(message: Message) -> None:
    """liga ou desliga o modo ausente"""
    global REASON, IS_AFK, TIME, TIPO, LINK  # pylint: disable=global-statement
    IS_AFK = True
    TIME = time.time()
    REASON = message.input_str
    if message.reply_to_message:
        try:
            link_ = await upload_media_(message)
            media = f"https://telegra.ph{link_}"
            LINK = media
            TIPO = link_type(LINK)
        except Exception:
            TIPO = "text"
    else:
        TIPO = "text"
    await asyncio.gather(
        CHANNEL.log(f"Ficando ausente.\n <i>{REASON}</i>"),
        message.edit(
            f"🥱 Ficando ausente, ate mais tarde.", del_in=5),
        AFK_COLLECTION.drop(),
        SAVED_SETTINGS.update_one(
            {"_id": "AFK"},
            {"$set": {"on": True, "data": REASON, "time": TIME, "tipo": TIPO, "link": LINK}},
            upsert=True,
        ),
    )


@kannax.on_filters(
    IS_AFK_FILTER
    & ~filters.me
    & ~filters.bot
    & ~filters.user(Config.TG_IDS)
    & ~filters.edited
    & (
        filters.mentioned
        | (
            filters.private
            & ~filters.service
            & (
                filters.create(lambda _, __, ___: Config.ALLOW_ALL_PMS)
                | Config.ALLOWED_CHATS
            )
        )
    ),
    allow_via_bot=False,
)
async def handle_afk_incomming(message: Message) -> None:
    """lida com ad mensagens recebidas quando você esta ausente"""
    if not message.from_user:
        return
    user_id = message.from_user.id
    chat = message.chat
    user_dict = await message.client.get_user_dict(user_id)
    afk_time = time_formatter(round(time.time() - TIME))
    coro_list = []
    if user_id in USERS:
        if not (USERS[user_id][0] + USERS[user_id][1]) % randint(2, 4):
            if REASON:
                out_str = (
                    f"▸ Oi, estou ausente a {afk_time}.\n"
                    f"▸ Motivo: <i>{REASON}</i>"
                )
            else:
                out_str = choice(AFK_REASONS)
            if TIPO == "anim":
                await message.reply_video(LINK, caption=out_str)
            elif TIPO == "photo":
                await message.reply_photo(LINK, caption=out_str)
            else:
                await message.reply(out_str)
        if chat.type == "private":
            USERS[user_id][0] += 1
        else:
            USERS[user_id][1] += 1
    else:
        if REASON:
            out_str = (
                f"▸ Oi, estou ausente a {afk_time}.\n"
                f"▸ Motivo: <i>{REASON}</i>"
            )
        else:
            afkout = rand_array(AFK_REASONS)
            out_str = f"<i>{afkout}</i>"
        if TIPO == "anim":
            await message.reply_video(LINK, caption=out_str)
        elif TIPO == "photo":
            await message.reply_photo(LINK, caption=out_str)
        else:
            await message.reply(out_str)
        if chat.type == "private":
            USERS[user_id] = [1, 0, user_dict["mention"]]
        else:
            USERS[user_id] = [0, 1, user_dict["mention"]]
    if chat.type == "private":
        coro_list.append(
            CHANNEL.log(
                f"#PRIVADO\n{user_dict['mention']} lhe enviou mensagens\n\n" f"Mensagem: <i>{message.text}</i>"
            )
        )
    else:
        coro_list.append(
            CHANNEL.log(
                "#GRUPO\n"
                f"{user_dict['mention']} mencionou você em [{chat.title}](http://t.me/{chat.username})\n\n"
                f"<i>{message.text}</i>\n\n"
                f"[Ver Mensagem](https://t.me/c/{str(chat.id)[4:]}/{message.message_id})"
            )
        )
    coro_list.append(
        AFK_COLLECTION.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "pcount": USERS[user_id][0],
                    "gcount": USERS[user_id][1],
                    "men": USERS[user_id][2],
                }
            },
            upsert=True,
        )
    )
    await asyncio.gather(*coro_list)


@kannax.on_filters(IS_AFK_FILTER & filters.outgoing, group=-1, allow_via_bot=False)
async def handle_afk_outgoing(message: Message) -> None:
    """lida com as mensagens de saida quando esta ausente"""
    global IS_AFK  # pylint: disable=global-statement
    IS_AFK = False
    afk_time = time_formatter(round(time.time() - TIME))
    replied: Message = await message.reply("`Não estou mais ausente!`", log=__name__)
    coro_list = []
    if USERS:
        p_msg = ""
        g_msg = ""
        p_count = 0
        g_count = 0
        for pcount, gcount, men in USERS.values():
            if pcount:
                p_msg += f"👤 {men} ✉️ **{pcount}**\n"
                p_count += pcount
            if gcount:
                g_msg += f"👥 {men} ✉️ **{gcount}**\n"
                g_count += gcount
        coro_list.append(
            replied.edit(
                f"`Você recebeu {p_count + g_count} mensagens enquanto você estava fora.`"
                f"`Verifique o log para obter mais detalhes.\n\nTempo ausente: {afk_time}`",
                del_in=3,
            )
        )
        out_str = (
            f"`Você recebeu {p_count + g_count} mensagens` "
            + f"`de {len(USERS)} usuários enquanto você estava fora!\nTempo ausente: {afk_time}`\n"
        )
        if p_count:
            out_str += f"\n**{p_count} Mensagens Privadas:**\n\n{p_msg}"
        if g_count:
            out_str += f"\n**{g_count} Mensagens de Grupo:**\n\n{g_msg}"
        coro_list.append(CHANNEL.log(out_str))
        USERS.clear()
    else:
        await asyncio.sleep(3)
        coro_list.append(replied.delete())
    coro_list.append(
        asyncio.gather(
            AFK_COLLECTION.drop(),
            SAVED_SETTINGS.update_one(
                {"_id": "AFK"}, {"$set": {"on": False}}, upsert=True
            ),
        )
    )
    await asyncio.gather(*coro_list)


def link_type(link):
    if link.endswith((".gif", ".mp4", "webm")):
        type_ = "anim"
    elif link.endswith((".jpeg", ".png", ".jpg", "webp")):
        type_ = "photo"
    else:
        type_ = "text"
    return type_


AFK_REASONS = (
    "Agora estou ocupado. Por favor, fale em uma bolsa e quando eu voltar você pode apenas me dar a bolsa!",
    "Estou fora agora. Se precisar de alguma coisa, deixe mensagem após o beep:\n`beeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeep`!",
    "Volto em alguns minutos e se não ..,\nespere mais um pouco.",
    "Não estou aqui agora, então provavelmente estou em outro lugar.",
    "Sei que quer falar comigo, mas estou ocupado salvando o mundo agora.",
    "Às vezes, vale a pena esperar pelas melhores coisas da vida…\nEstou ausente então espere por mim.",
    "Olá, seja bem-vindo à minha mensagem de ausência, como posso ignorá-lo hoje?",
    "Estou mais longe que 7 mares e 7 países,\n7 águas e 7 continentes,\n7 montanhas e 7 colinas,\n7 planícies e 7 montes,\n7 piscinas e 7 lagos,\n7 nascentes e 7 prados,\n7 cidades e 7 bairros,\n7 quadras e 7 casas...\n\nOnde nem mesmo suas mensagens podem me alcançar!",
    "Estou ausente no momento, mas se você gritar alto o suficiente na tela, talvez eu possa ouvir você.",
    "Por favor, deixe uma mensagem e me faça sentir ainda mais importante do que já sou.",
    "Eu não estou aqui então pare de escrever para mim,\nou então você se verá com uma tela cheia de suas próprias mensagens.",
    "Se eu estivesse aqui,\nEu te diria onde estou.\n\nMas eu não estou,\nentão me pergunte quando eu voltar...",
    "Não estou disponível agora, por favor, deixe seu nome, número e endereço e eu irei persegui-lo mais tarde. ",
    "Desculpe, eu não estou aqui agora.\nSinta-se à vontade para falar com meu userbot pelo tempo que desejar.\nEu respondo mais tarde.",
    "A vida é tão curta, há tantas coisas para fazer ...\nEstou ausente fazendo uma delas ..",
    "Eu não estou aqui agora ...\nmas se estivesse...\n\nisso não seria incrível?",
)

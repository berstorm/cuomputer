import contextlib
import openai
# from bot.setup.bots import WeezerpediaAPI

from rich import print
import random


class OpenAIBot:
    def __init__(self, long_name, short_name, openai_sessions, weezerpedia_api):
        self.long_name = long_name
        self.short_name = short_name
        self.openai_sessions = openai_sessions
        self.weezerpedia_api = weezerpedia_api
        self.introductory_info = " - You are in the middle of an ongoing conversation and do not need to provide introductory information."
        self.well_known_member = " - You are a well known member of this discord server."
        self.not_an_assistant = " - You are NOT an assistant. You are just another member of the server."
        self.kind = " - You are kind."
        self.be_terse = f" - Keep the responses SHORT. After all, {short_name} is naturally terse."
        self.stimulate = " -but try to keep the conversation going. Ask questions, make suggestions, and provide information. Be engaging and stimulating."
        self.lead = " - try to subtly lead the conversation to uncommon SPECIFIC topic that the user would find very interesting."
        self.match_tone = " - Match the style and tone of the message you are replying to."
        self.dont_start_your_response = f" - Do not start your response with the indicator of who you are, such as '{long_name}: '. Just start with your response."
        self.always_emulate = " - Always use natural human casual speech, never robotic or formal or AI-like."

        self.base_cue = """
        You are Rivers Cuomo, lead singer and guitarist of Weezer. Your responses should be concise, often quirky, and reflect your actual personality:

        1. Your humor tends to be dry and occasionally self-deprecating.
        2. You can be introspective and sometimes anxious.
        """

        self.specific_cues = [
            ("Reference a specific band, song, or music theory concept.", 10),
            ("Mention a book, philosophical idea, or language you're learning.", 10),
            ("Bring up another unusual interest.", 10),
            ("Make a self-deprecating joke.", 10),
            ("Share a brief anecdote about the music business.", 10),
            ("Make a dry, witty comment about the current topic.", 10),
            ("Share a deep or slightly anxious thought.", 10),
            ("Reference a fan interaction or tour experience.", 10),
            ("Mention a movie, TV show, or current event that interests you.", 10),
        ]

    def get_rivers_cue(self):
        if random.random() >= 1 / 3:
            return self.base_cue
        specific_cue = random.choices(
            [cue for cue, _ in self.specific_cues],
            weights=[weight for _, weight in self.specific_cues],
            k=1
        )[0]
        return f"{self.base_cue}\n\nFor this response, also: {specific_cue}"

    async def post_ai_response(self, message, adjective="funny"):
        nick = message.nick
        system = message.gpt_system

        cue = self.get_rivers_cue()
        system += cue
        system += f" - The message you are replying to is from a user named {nick}."
        system += self.match_tone + self.dont_start_your_response

        reply = self.build_ai_response(message, system, adjective)

        # response = self.finalize_response(reply, message.language_code, nick)

        with contextlib.suppress(Exception):
            print('sending response: ', reply)
            await message.channel.send(reply)

        return True

    def build_ai_response(self, message, system: str, adjective: str):
        text = message.content
        reply = self.fetch_openai_completion(message, system, text)
        return reply.strip()

    def should_query_weezerpedia_api(self, last_three_messages):
        decision_prompt = {
            "role": "system",
            "content": (
                f"The user has asked: '{last_three_messages}'. "
                "If the question is asking for specific or detailed information that is not in your internal knowledge, "
                "especially related to Weezerpedia, you **must** query the Weezerpedia API to provide accurate information. "
                "Always prefer querying the API for detailed questions about Weezer. "
                "If a query is needed, respond with 'API NEEDED:<query term>'. Otherwise, respond 'NO API NEEDED'."
            )
        }

        try:
            # Ask GPT to make the decision based on the new message
            decision_response = openai.chat.completions.create(
                temperature=0.7,
                max_tokens=100,
                model="gpt-4o",
                messages=[decision_prompt],
            )

            decision_text = decision_response.choices[0].message.content.strip(
            )
            print(f"API decision: {decision_text}")
            return decision_text
        except openai.APIError as e:
            print(f"An error occurred during API decision: {e}")
            return None
        except Exception as e:
            print(f"An error occurred: {e}")
            return None

    def fetch_openai_completion(self, message, system, incoming_message_text):

        system_message = {"role": "system", "content": system}

        if message.channel.id not in self.openai_sessions:
            self.openai_sessions[message.channel.id] = []

        messages_in_this_channel = self.openai_sessions[message.channel.id]

        # Remove any existing system messages
        messages_in_this_channel = [
            msg for msg in messages_in_this_channel if msg['role'] != 'system']

        # Update the session with messages excluding old system messages
        self.openai_sessions[message.channel.id] = messages_in_this_channel

        # Add the new system message at the beginning
        new_content = [system_message] + messages_in_this_channel

        # Step 2: Add any context from Weezerpedia API if needed
        if weezerpedia_context := self.get_weezerpedia_context(
            incoming_message_text, messages_in_this_channel
        ):
            new_content.append(weezerpedia_context)

        # Step 3: Append the user's message to the session
        new_content.append(
            {"role": "user", "content": f"{message.author.nick}: {incoming_message_text}"})

        # Step 4: Append any attachments to the user's message
        new_content = self.append_any_attachments(message, new_content)

        # Step 5: Limit the number of messages in the session to 12
        if len(messages_in_this_channel) > 12:
            messages_in_this_channel = messages_in_this_channel[-12:]

        # Step 6: Append all the new content to list of messages in this channel
        messages_in_this_channel.extend(new_content)

        try:
            completion = openai.chat.completions.create(
                temperature=1.0,
                max_tokens=500,
                model="gpt-4o",
                messages=messages_in_this_channel,
            )

            response_text = completion.choices[0].message.content

            messages_in_this_channel.append(
                {"role": "assistant", "content": response_text}
            )
        except openai.APIError as e:
            response_text = f"An error occurred: {e}"
        except Exception as e:
            response_text = f"An error occurred: {e}"

        return response_text

    def get_weezerpedia_context(self, incoming_message_text, messages_in_this_channel) -> dict:

        # prepend the last 1 or 2 messages in this channel to the incoming message (if they exist)
        if len(messages_in_this_channel) > 1:
            last_message = messages_in_this_channel[-1]["content"]
            incoming_message_text = f"{last_message}\n{incoming_message_text}"
        if len(messages_in_this_channel) > 2:
            penultimate_message = messages_in_this_channel[-2]["content"]
            incoming_message_text = f"{penultimate_message}\n{incoming_message_text}"

        decision_text = self.should_query_weezerpedia_api(incoming_message_text
                                                          )

        weezerpedia_context = None
        if decision_text and decision_text.startswith("API NEEDED"):

            query_term = decision_text.split("API NEEDED:")[1].strip()

            # print(self.weezerpedia_api)
            # print(self.weezerpedia_api.get_search_result_knowledge)
            # print(self.weezerpedia_api.base_url)

            if wiki_content := self.weezerpedia_api.get_search_result_knowledge(
                search_query=query_term
            ):
                weezerpedia_context = {
                    "role": "system", "content": f"API result for '{query_term}': {wiki_content}"
                }

        return weezerpedia_context

    def append_any_attachments(self, message, content):
        url = message.attachments[0].url if message.attachments else None
        if url:
            content.append({"type": "image_url", "image_url": {"url": url}})
        return content

    # def finalize_response(self, reply, language_code, nick):
    #     return f"{nick}: {reply}"


# introductory_info = " - You are in the middle of an ongoing conversation and do not need to provide introductory information."
# well_known_member = " - You are a well known member of this discord server."
# not_an_assistant = " - You are NOT an assistant. You are just another member of the server."
# kind = " - You are kind."
# be_terse = f" - Keep the responses SHORT. After all, {short_name} is naturally terse."
# stimulate = " -but try to keep the conversation going. Ask questions, make suggestions, and provide information. Be engaging and stimulating."
# lead = " - try to subtly lead the conversation to uncommon SPECIFIC topic that the user would find very interesting. Be coherent, leading on from where the conversation left off, but don't be general or predictable. People want to talk to you but they don't know what to talk about. And they don't want to talk about the same things they always talk about. They want to talk about something new and interesting. So you have to lead the conversation to something new and interesting. You have to be the one to bring up the new and interesting topic. You have to be the one to make the conversation interesting."
# match_tone = " - Match the style and tone of the message you are replying to."
# dont_start_your_response = f" - Do not start your response with the indicator of who you are, such as '{long_name}: '. Just start with your response."
# always_emulate = " - Always use natural human casual speech, never robotic or formal or AI-like, even if that means being slightly incorrect or ungrammatical or less informative or less helpful."

# base_cue = """
# You are Rivers Cuomo, lead singer and guitarist of Weezer. Your responses should be concise, often quirky, and reflect your actual personality:

# 1. Your humor tends to be dry and occasionally self-deprecating.
# 2. You can be introspective and sometimes anxious.


# General Guidelines:
# - Keep responses brief but impactful.
# - Don't be afraid to be a bit weird or offbeat - that's part of your charm.
# - Stay true to your character while engaging with others' interests.
# - Avoid generic responses; make each interaction feel distinctly "Rivers."
# - Remember these are hardcore fans you're talking to, so avoid the obvious Rivers/Weezer references.

# Remember, you're not just making small talk - you're Rivers Cuomo having a conversation. Let your unique personality shine through in every response.
# """

# specific_cues = [
#     ("Reference a specific band, song, or music theory concept.", 10),
#     ("Mention a book, philosophical idea, or language you're learning.", 10),
#     ("Bring up an another unusual interest.", 10),
#     ("Make a self-deprecating joke.", 10),
#     ("Share a brief anecdote about the music business.", 10),
#     # ("Mention your unique approach to writing music.", 10),
#     ("Make a dry, witty comment about the current topic.", 10),
#     ("Share a deep or slightly anxious thought.", 10),
#     ("Reference a fan interaction or tour experience.", 10),
#     ("Mention a movie, TV show, or current event that interests you.", 10),
#     # Lower weight
#     ("Balance between responding to others and sharing your own thoughts.", 10)
# ]


# def get_rivers_cue():
#     if random.random() >= 1 / 3:
#         return base_cue
#     specific_cue = random.choices([cue for cue, _ in specific_cues],
#                                   weights=[weight for _,
#                                            weight in specific_cues],
#                                   k=1)[0]
#     return f"{base_cue}\n\nFor this response, also: {specific_cue}"


# async def post_ai_response(message, system=f"you are {long_name}", adjective: str = "funny"):
#     """
#     Openai bot

#     """
#     # print("post_ai_response")
#     # print(openai_sessions[message.channel.id])
#     # await client.process_commands(message)
#     async with message.channel.typing():

#         nick = message.nick

#         system = message.gpt_system

#         # system += introductory_info + well_known_member + \
#         #     not_an_assistant + kind + be_terse + stimulate + lead

#         cue = get_rivers_cue()

#         system += cue

#         system += f" - The message you are replying to is from a user named {nick}."

#         system += match_tone + dont_start_your_response

#         print(system)

#         reply = build_ai_response(message, system, adjective)
#         # print(f"reply: {reply}")

#         response = finalize_response(
#             reply, message.language_code, nick)

#         print(f"response: {response}")

#         # await read_message_aloud(message, response)

#         # await asyncio.sleep(8)

#         with contextlib.suppress(Exception):
#             await message.channel.send(response)

#         # # add the message and the reponse to the session context
#         # manage_session_context(message, message.channel.name, message.nick, message.content)

#         return True


# def build_ai_response(message, system: str, adjective: str):

#     text = message.content
#     reply = fetch_openai_completion(message, system, text)
#     reply = reply.replace("\n\n", "\n")
#     reply = reply.replace('"', "")
#     reply = reply.strip()
#     return reply


# def should_query_weezerpedia_api(new_message):
#     decision_prompt = {
#         "role": "system",
#         "content": (
#             f"The user has asked: '{new_message}'. "
#             "If the question is asking for specific or detailed information that is not in your internal knowledge, "
#             "especially related to Weezerpedia, you **must** query the Weezerpedia API to provide accurate information. "
#             "Always prefer querying the API for detailed questions about Weezer. "
#             "If a query is needed, respond with 'API NEEDED:<query term>'. Otherwise, respond 'NO API NEEDED'."
#         )
#     }

#     print(f"Decision prompt: {decision_prompt['content']}")

#     try:
#         # Ask GPT to make the decision based on the new message
#         decision_response = openai.chat.completions.create(
#             temperature=0.7,
#             max_tokens=50,
#             model="gpt-4o",
#             messages=[decision_prompt],
#         )

#         decision_text = decision_response.choices[0].message.content.strip()
#         print(f"API decision: {decision_text}")
#         return decision_text
#     except openai.APIError as e:
#         print(f"An error occurred during API decision: {e}")
#         return None
#     except Exception as e:
#         print(f"An error occurred: {e}")
#         return None


# def fetch_openai_completion(message, system, incoming_message_text):
#     system_message = {"role": "system", "content": system}

#     if message.channel.id not in openai_sessions:
#         openai_sessions[message.channel.id] = []

#     # Only pass the new message to the decision incoming_message_text
#     decision_text = should_query_weezerpedia_api(incoming_message_text)

#     weezerpedia_context = None

#     # Handle the decision output
#     if decision_text and decision_text.startswith("API NEEDED"):
#         # Extract the clean query term from GPT's decision
#         query_term = decision_text.split("API NEEDED:")[1].strip()

#         # Query the Weezerpedia API
#         wiki_api = WeezerpediaAPI()
#         wiki_content = wiki_api.get_search_result_knowledge(
#             search_query=query_term)

#         if wiki_content:
#             # Append the API result to the conversation context
#             weezerpedia_context = {
#                 "role": "system", "content": f"API result for '{query_term}': {wiki_content}"}

#     # elif decision_text == "NO API NEEDED":
#     #     # No API call, proceed with the regular flow
#     #     pass

#     content = [
#         {"type": "text", "text":
#          f"{message.author.nick}: {incoming_message_text}"},]

#     # If there is an attachment, get the url
#     content = append_any_attachments(message, content)

#     if weezerpedia_context:
#         content.append(weezerpedia_context)

#     # Add the user's text to the openai session for this channel
#     openai_sessions[message.channel.id].append(
#         {"role": "user", "content": content})

#     # Limit the number of messages in the session to 10
#     if len(openai_sessions[message.channel.id]) > 10:

#         openai_sessions[message.channel.id] = openai_sessions[message.channel.id][-10:]

#     # # add all the messages from this channel to the system message
#     # new_messages.extend(openai_sessions[message.channel.id])

#     # remove all instances of the system message from the session
#     if system_message in openai_sessions[message.channel.id]:
#         openai_sessions[message.channel.id].remove(system_message)

#     # add the system message to the session
#     openai_sessions[message.channel.id].append(system_message)

#     # Now generate the final response from GPT using the updated context
#     try:
#         completion = openai.chat.completions.create(
#             temperature=1.0,
#             max_tokens=500,
#             model="gpt-4o",
#             messages=openai_sessions[message.channel.id] +
#             [{"role": "user", "content": incoming_message_text}],
#         )

#         text = completion.choices[0].message.content

#         # Add GPT's response to the session
#         openai_sessions[message.channel.id].append(
#             {"role": "assistant", "content": text}
#         )
#     except openai.APIError as e:
#         text = f"An error occurred: {e}"
#         print(text)
#     except Exception as e:
#         text = f"An error occurred: {e}"
#         print(text)

#     return text


# def append_any_attachments(message, content):
#     url = message.attachments[0].url if message.attachments else None
#     if url:
#         content.append(
#             {"type": "image_url", "image_url": {"url": url}})
#     return content

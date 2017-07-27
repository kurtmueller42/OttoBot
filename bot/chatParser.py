import globalSettings
from dataContainers import Command

import logging
import asyncio

_logger = logging.getLogger()

class ChatParser():
    def __init__(self, prefix, db, functionExecutor):
            self.db = db
            self.prefix = prefix
            self.function_executor = functionExecutor
            
            self.command_types = None
            self.commands = None
            self.responses = None
            self.load_from_database()

    def load_from_database(self):
        _logger.info("dumping everything and loading from the database")
        self.command_types = {}
        self.commands = {}
        self.responses = {}
        
        for ct in self.db.get_command_types():
            self.command_types[ct.id] = ct
        
        for cmd in self.db.get_active_commands():
            self.commands[cmd.id] = cmd
            self.load_responses_from_database(cmd.id)
        _logger.info("finished loading")
    
    def load_responses_from_database(self, command_id):
        self.responses[command_id] = {}
        for resp in self.db.get_responses(command_id):
            self.responses[command_id][resp.id] = resp
        _logger.info("done loading responses for command: " + str(command_id))

    def get_first_response(self, command_id):
        for r in self.responses[command_id]:
            if self.responses[command_id][r].previous == None:
                return self.responses[command_id][r]

    def get_last_response(self, command_id):
        for r in self.responses[command_id]:
            if self.responses[command_id][r].next == None:
                return self.responses[command_id][r]

    def get_command_type_id(self, name):
        for cmd_type in self.command_types:
            if self.command_types[cmd_type].name == name:
                return self.command_types[cmd_type].id

    def add_command(self, cmd, response):
        if not isinstance(cmd, Command):
            raise TypeError("cmd must be a Command object")
        if not cmd.text.startswith(self.prefix):
            cmd.text = self.prefix + cmd.text
        _logger.info("starting to create cmd: " + cmd.text)
        
        #check to see if this command already exists
        insert = True
        for c in self.commands:
            if self.commands[c].is_equivalent_matcher(cmd):
                insert = False
                cmd = self.commands[c]
        
        if insert:
            cmd.id = self.db.insert_command(cmd.text, cmd.removable, cmd.case_sensitive, cmd.command_type_id)
            self.commands[cmd.id] = cmd
            self.responses[cmd.id] = {}

        prev = self.get_last_response(cmd.id)
        if prev:
            prev = prev.id
        self.db.insert_response(response.text, response.function, prev, cmd.id)
        self.load_responses_from_database(cmd.id)
    
    def delete_response(self, response):
        self.db.delete_response(response.id, response.next, response.previous)
        
        #reload from the database, since the db function takes care of logic for use
        self.responses[response.command_id] = {}
        for resp in self.db.get_responses(response.command_id):
            self.responses[response.command_id][resp.id] = resp
        
        #if we now have an empty list of responses, then deactivate the command
        if len(self.responses[response.command_id]) == 0:
            self.db.deactivate_command(response.command_id)

    def is_match(self, command, text):
        to_match = command.text
        if not command.case_sensitive:
            to_match = to_match.upper()
            text = text.upper()
        if self.command_types[command.command_type_id].name == 'STARTS_WITH':
            return text.startswith(to_match)
        elif self.command_types[command.command_type_id].name == 'CONTAINS':
            return to_match in text
        elif self.command_types[command.command_type_id].name == 'EQUALS':
            return to_match == text
        else:
            _logger.warn("Unknown command type: " + self.command_types[command.command_type_id].name)

    def get_replies(self, message, bot, web):
        """this yields strings until it has completed its reply"""
        for i in self.commands:
            cmd = self.commands[i]
            if self.is_match(cmd, message.content):
                _logger.info("Matched %s to command %s", message.content, cmd.text)
                request_id = self.db.insert_request(message.author.name, cmd.id)
                response = self.get_first_response(cmd.id)
                return self.get_responses(cmd.id, response.id, request_id, message, bot, web)

    #helper function to encapsulate response logic (for use with pending responses)
    async def get_responses(self, command_id, response_id, request_id, message, bot, web):
        response = self.responses[command_id][response_id]
        while response:
            _logger.info("getting response: " + str(response.id))
            if response.text:
                yield response.text
            elif response.function:
                result = await self.function_executor.execute(response.function, request_id, response.id, message, bot, self, web)
                yield result[0]
                if not result[1]:
                    break
            else:
                _logger.warn("empty response: " + str(response.id))
            if response.next:
                response = self.responses[command_id][response.next]
            else:
                break
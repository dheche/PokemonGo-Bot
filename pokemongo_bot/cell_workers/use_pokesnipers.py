# -*- coding: utf-8 -*-

import os
import time
from datetime import datetime
from collections import deque
import json
import requests
from pokemongo_bot.worker_result import WorkerResult
from pokemongo_bot.base_task import BaseTask
from pokemongo_bot.cell_workers.pokemon_catch_worker import PokemonCatchWorker


class UsePokesnipers(BaseTask):
    SUPPORTED_TASK_API_VERSION = 1

    def initialize(self):
        self.api = self.bot.api
        self.pokemon_data = self.bot.pokemon_list
        self.vips = self.bot.config.vips
        self.suppress_downtime_log = 0
        self.suppress_log = False
        self.max_snipe_per_check = self.config['max_snipe_per_check']
        self.last_target_list = 0
        self.seen_locations = deque()

    def work(self):
        now = int(time.time())
        if (now - self.last_target_list > self.config['min_time']):
            locations = self.get_locations_from_pokesnipers()
            self.last_target_list = now
        else:
            return WorkerResult.SUCCESS

        counter = 1
        for location in locations:
            if counter > self.max_snipe_per_check:
                break
            now = datetime.utcnow()
            future = datetime.strptime(location['until'], '%Y-%m-%dT%H:%M:%S.000Z')
            if (future - now).total_seconds() > 20 and (future - now).total_seconds() < 650 and location['id'] not in self.seen_locations:
                self.seen_locations.append(location['id'])
                self._emit_log('['+str(counter)+'/'+str(self.max_snipe_per_check)+'] Pokemon target is: '+location['name'])
                self.snipe_pokemon(location['coords'], counter)
                counter += 1
                if len(self.seen_locations) > 10:
                    self.seen_locations.popleft()

        return WorkerResult.SUCCESS

    def get_locations_from_pokesnipers(self):
        locations = []
        try:
            req = requests.get('http://pokesnipers.com/api/v1/pokemon.json')
            raw_data = req.json()
            locations = raw_data['results']
        except Exception:
            if self.suppress_downtime_log % 50 == 0:
                self._emit_log('Could not reach PokeSnipers server, or invalid data.')
            self.suppress_downtime_log += 1
            return []

        self.suppress_downtime_log = 0

        return locations

    def snipe_pokemon(self, location, seq):
        original_location = self.bot.position
        orig_lat, orig_lon, orig_alt = original_location

        self.bot.heartbeat()

        lat, lng = location.split(',')
        if not self.suppress_log:
            self._teleport_to(lat,lng)
        self.api.set_position(float(lat), float(lng), 0)
        time.sleep(5)
        self.cell = self.bot.get_meta_cell()

        target_pokemon = None
        if 'catchable_pokemons' in self.cell and len(self.cell['catchable_pokemons']) > 0:
            for pokemon in self.cell['catchable_pokemons']:
                pokemon_num = int(pokemon['pokemon_id']) - 1
                pokemon_name = self.pokemon_data[int(pokemon_num)]['Name']
                if pokemon_name in self.vips:
                    self._emit_log('Sniping '+pokemon_name+'...')
                    target_pokemon = pokemon
                    self.suppress_log = False
                    break

        if not target_pokemon:
            if not self.suppress_log:
                self._teleport_to(orig_lat,orig_lon,'No Pokemon found, teleporting back to prev location ')
            self.api.set_position(*original_location)
            if self.max_snipe_per_check == seq:
                time.sleep(10)
            #self.suppress_log = True
            return

        catch_worker = PokemonCatchWorker(target_pokemon, self.bot)
        api_encounter_response = catch_worker.create_encounter_api_call()

        time.sleep(2)
        if not self.suppress_log:
            self._teleport_to(orig_lat,orig_lon,'Teleporting back to prev location ')
        self.api.set_position(*original_location)
        time.sleep(2)

        self.bot.heartbeat()

        catch_worker.work(api_encounter_response)

    def _emit_log(self, msg):
        """Emits log to event log.
        
        Args:
            msg: Message to emit
        """
        self.emit_event(
            'use_pokesnipers', 
            formatted='{message}',
            data={'message': msg}
        )
    def _teleport_to(self, lat, lon, msg1="Teleporting to ", msg2=""):
        """Emits log to event log.
        
        Args:
            lat: latitude
            lon: longitude
            msg1: Prefix message to emit
            msg2: Suffix message to emit
        """
        self.emit_event(
            'teleport_to', 
            formatted='{prefix}({latitude},{longitude}){suffix}',
            data={'latitude': lat, 'longitude': lon, 'prefix': msg1, 'suffix': msg2}
        )
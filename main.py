import requests
import pandas as pd
import numpy as np
import aiohttp
import asyncio
from time import time
import sys
import os

# Alot of this code is inspired https://towardsdatascience.com/fantasy-premier-league-value-analysis-python-tutorial-using-the-fpl-api-8031edfe9910
# Big thanks to David Allen for the tutorials. This script is simply adding extra data on top of the original post above.

# Remove warning about chaining value assignment. Not needed as I dont need original data
pd.options.mode.chained_assignment = None  # default='warn'

# Retrieving JSON Data
base_url = 'https://fantasy.premierleague.com/api/'
current_stats_url = base_url + 'bootstrap-static/'
individual_stats_url = base_url + 'element-summary/'
r = requests.get(current_stats_url)
json = r.json()

# Seperating data into panda DBs
elements_df = pd.DataFrame(json['elements'])
elements_types_df = pd.DataFrame(json['element_types'])
teams_df = pd.DataFrame(json['teams'])

# Grabbing only relevant data
slim_elements_df = elements_df[['id', 'second_name', 'team',
                                'element_type', 'now_cost', 'minutes', 'value_season', 'total_points']]
slim_team_df = teams_df[['name', 'strength_overall_home', 'strength_overall_away',
                         'strength_attack_home', 'strength_attack_away', 'strength_defence_home', 'strength_defence_away']]

# Adding relevant team and position data
slim_elements_df['position'] = slim_elements_df.element_type.map(
    elements_types_df.set_index('id').singular_name)
slim_elements_df['team'] = slim_elements_df.team.map(
    teams_df.set_index('id').name)

# Setting value column to float so it can be sorted and removing players with zero minutes
slim_elements_df['value'] = slim_elements_df.value_season.astype(float)
slim_elements_df = slim_elements_df.loc[slim_elements_df.value > 0]

# Setting columns for opposition difficulties
slim_elements_df['next_difficulty'] = 0
slim_elements_df['average_5_difficulty'] = 0
slim_elements_df['average_all_difficulty'] = 0

# This column states the difficulty of the oppoisitions 'opposite' position strength.
# E.g. If the player is a defender and playing at home, the oppositions team attack strength away.
slim_elements_df['opposition_position_difficulty'] = 0

# Progress bar


def progress(count, total, status=''):
    bar_len = 60
    filled_len = int(round(bar_len * count / float(total)))

    percents = round(100.0 * count / float(total), 1)
    bar = '=' * filled_len + '-' * (bar_len - filled_len)

    # Clearing line as we dont know length of final output
    sys.stdout.write(' ' * 100 + '\r')

    # Writing then flushing the progress bar
    sys.stdout.write('[%s] %s%s - %s\r' % (bar, percents, '%', status))
    sys.stdout.flush()

async def get_player_info(session, url, current_index, name):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.77 Safari/537.36"}

    async with session.get(url, headers=headers) as resp:
        progress(current_index, len(slim_elements_df), status=name)
        return await resp.json()


async def main():
    async with aiohttp.ClientSession() as session:
        tasks = []
        current_index = 0

        # Iterating over all players indexs
        for element_id in slim_elements_df.id:
            current_index += 1
            url = f'{individual_stats_url}{element_id}/'
            name = slim_elements_df.loc[slim_elements_df['id']
                                        == element_id, 'second_name']

            tasks.append(asyncio.ensure_future(
                get_player_info(session, url, current_index, name.values[0])))

            player_tasks = await asyncio.gather(*tasks)

            # Iterating over all player stats
            for player in player_tasks:

                # Renaming commonly used db calls because I was getting too confused what I was using
                player_info = slim_elements_df.loc[slim_elements_df.id == element_id]
                team = player_info['team'].values
                position = player_info['position'].values[0]
                team_info = slim_team_df.loc[slim_team_df['name'].values == team]

                # Accesing future fixtures and finding difficulty of games
                json_fixtures_df = pd.DataFrame(player['fixtures'])
                player_info['next_difficulty'] = json_fixtures_df.at[0, 'difficulty']
                player_info['average_5_difficulty'] = json_fixtures_df[:5]['difficulty'].mean()
                player_info['average_all_difficulty'] = json_fixtures_df['difficulty'].mean()

                next_game_is_home = json_fixtures_df.at[0, 'is_home']

                # Specifying specific difficulty of next game based on player position and opposition strength
                if(position == 'Defender' or
                   position == 'Goalkeeper'):
                    if(next_game_is_home):
                        player_info['opposition_position_difficulty'] = team_info['strength_attack_away'].values
                    else:
                        player_info['opposition_position_difficulty'] = team_info['strength_attack_home'].values
                else:
                    if(next_game_is_home):
                        player_info['opposition_position_difficulty'] = team_info['strength_defence_away'].values
                    else:
                        player_info['opposition_position_difficulty'] = team_info['strength_defence_home'].values

                # Updating the db with new values
                slim_elements_df.loc[slim_elements_df.id ==
                                     element_id] = player_info


def export():
    # You should change 'test' to your preferred folder.
    export_dir = ("exports")
    check_folder = os.path.isdir(export_dir)

    # If folder doesn't exist, then create it.
    if not check_folder:
        os.makedirs(export_dir)

    # Ordering by value for price
    value_for_price = slim_elements_df.sort_values('value', ascending=False)

    # Getting best valued positions
    position_pivot = slim_elements_df.pivot_table(
        index='position', values='value', aggfunc=np.mean).reset_index().sort_values('value', ascending=False)

    # Getting best values teams
    team_pivot = slim_elements_df.pivot_table(
        index='team', values='value', aggfunc=np.mean).reset_index().sort_values('value', ascending=False)

    # Getting best value of positions again but specifically for each position
    fwd_df = slim_elements_df.loc[slim_elements_df.position == 'Forward'].sort_values(
        'value', ascending=False)
    mid_df = slim_elements_df.loc[slim_elements_df.position ==
                                  'Midfielder'].sort_values('value', ascending=False)
    def_df = slim_elements_df.loc[slim_elements_df.position == 'Defender'].sort_values(
        'value', ascending=False)
    goal_df = slim_elements_df.loc[slim_elements_df.position ==
                                   'Goalkeeper'].sort_values('value', ascending=False)

    # Converting DBs to CSV
    value_for_price.to_csv(f'{export_dir}/all_fpl_data.csv')
    position_pivot.to_csv(f'{export_dir}/position_fpl_data.csv')
    team_pivot.to_csv(f'{export_dir}/team_fpl_data.csv')
    goal_df.to_csv(f'{export_dir}/goal_fpl_data.csv')
    def_df.to_csv(f'{export_dir}/def_fpl_data.csv')
    mid_df.to_csv(f'{export_dir}/mid_fpl_data.csv')
    fwd_df.to_csv(f'{export_dir}/fwd_fpl_data.csv')


if __name__ == '__main__':
    start_time = time()

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
    export()

    end_time = time()

    print(f'\nTotal time: {end_time - start_time} seconds')

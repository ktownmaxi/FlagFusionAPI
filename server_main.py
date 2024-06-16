import os
import queue
import random
from glob import glob
from io import BytesIO
from zipfile import ZipFile

from flask import Flask, request, send_file
from flask_restful import Api, Resource, reqparse
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
api = Api(app)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///player_data.db"
db = SQLAlchemy(app)

current_dir = os.path.dirname(os.path.abspath(__file__))


class MatchmakingDB(db.Model):
    """
    Class for storing matchmaking data
    """
    playerID = db.Column(db.Integer, primary_key=True)
    playerScore = db.Column(db.Integer, nullable=False)
    matchedPlayer = db.Column(db.Integer, nullable=True)
    gameFinished = db.Column(db.Boolean, nullable=True)


class PlayerDB(db.Model):
    """
    Database for storing Player related data
    """
    playerID = db.Column(db.Integer, primary_key=True, nullable=False)
    playerName = db.Column(db.String(255), nullable=True)
    avatar = db.Column(db.String(255), nullable=True)
    nationality = db.Column(db.String(255), nullable=True)


with app.app_context():
    db.create_all()

player_queue = queue.Queue()
final_flags = []


class Matchmaking(Resource):
    def __init__(self):
        self.join_queue_args = reqparse.RequestParser()
        self.join_queue_args.add_argument("playerID", type=float, help="Player ID - Required")

    def put(self):
        """
        Method for registering players, putting them on a waiting list and generating DB entries.
        :returns: {"started_matchmaking": bool, "playerID": int, "opponentID": int}, int
        """

        args = self.join_queue_args.parse_args()
        if args["playerID"]:
            if player_queue.empty():
                playerID = args["playerID"]
                original_player = MatchmakingDB.query.filter_by(playerID=args["playerID"]).first()
                if original_player is not None:
                    db.session.delete(original_player)
                    db.session.commit()

                player_queue.put(playerID)

                global final_flags
                final_flags = CommunicationAPI.create_flag_list()

                new_entry = MatchmakingDB(playerID=playerID, playerScore=0, gameFinished=False)
                db.session.add(new_entry)
                db.session.commit()

                return {"started_matchmaking": False,
                        "playerID": playerID,
                        "opponentID": 0}, 200
            else:
                original_player = MatchmakingDB.query.filter_by(playerID=args["playerID"]).first()
                if original_player is not None:
                    db.session.delete(original_player)
                    db.session.commit()

                player_2_id = args["playerID"]
                player_1_id = player_queue.get()

                new_entry = MatchmakingDB(playerID=args["playerID"], playerScore=0,
                                          matchedPlayer=int(player_1_id), gameFinished=False)
                db.session.add(new_entry)

                player = MatchmakingDB.query.filter_by(playerID=player_1_id).first()
                if player is not None:
                    player.matchedPlayer = player_2_id

                db.session.commit()

                return {"started_matchmaking": True,
                        "playerID": player_2_id,
                        "opponentID": player_1_id}, 200
        else:
            return {"started_matchmaking": False, "playerID": None}, 401

    def post(self):
        """
        Method for checking if matchmaking started for the inputted player
        :returns: {"started_matchmaking": bool, "opponentID": int}, int
        """

        matchmaking_status_args = reqparse.RequestParser()
        matchmaking_status_args.add_argument("playerID", type=int, help="Player ID to identify Player")

        args = matchmaking_status_args.parse_args()

        player = MatchmakingDB.query.filter_by(playerID=args["playerID"]).first()
        if player and not player_queue.empty():
            return {"started_matchmaking": False,
                    "opponentID": player.matchedPlayer}, 200
        if player and player_queue.empty():
            return {"started_matchmaking": True,
                    "opponentID": player.matchedPlayer}, 200
        else:
            print("Player not found in DB")
            return "Player not registered", 401

    def patch(self):
        """
        Method for removing player from queue
        :returns: {"message": "Successfully removed player from queue"}, int
        """
        matchmaking_status_args = reqparse.RequestParser()
        matchmaking_status_args.add_argument("playerID", type=int, help="Player ID to identify Player")

        args = matchmaking_status_args.parse_args()

        try:
            player_queue.queue.remove(args["playerID"])
            return {"message": "Successfully removed player from queue"}, 200

        except Exception:
            return {"message": "Could not find player with this ID in queue"}, 400


class CommunicationAPI(Resource):

    def __init__(self):
        self.score_patch_args = reqparse.RequestParser()
        self.score_patch_args.add_argument("score", type=int, help="Current score of the player")
        self.score_patch_args.add_argument("id", type=float, help="Player ID - Required")

    @staticmethod
    def detect_duplicates(my_list: list) -> bool:
        """
        Method to detect duplicates in a given list.
        :param my_list: list which should be checked on duplicates.
        :return: returns a bool if a duplicate was detected
        """
        duplicates = False
        for value in my_list:
            if my_list.count(value) > 1:
                duplicates = True
            else:
                pass
        return duplicates

    @staticmethod
    def read_countrynames() -> list:
        """
        Method to read a json file
            :param path json_file_path: Path to find the json file.
            :returns : Returns a Dictionary with the information from the file
            :rtype : Returns a Dictionary
            :raises anyError: if something goes wrong
        """

        with open(os.path.join(current_dir, "countrynames.txt"), 'r') as file:
            # Lies den gesamten Inhalt der Datei
            data = file.read()
        strings = data.split(';')
        string_liste = [s.strip() for s in strings]
        return string_liste

    @staticmethod
    def create_flag_list() -> list:
        """
        Method to create a list with 20 items of random flag file names
        :return: a list of the chosen countries
        """
        flag_file_names = CommunicationAPI.read_countrynames()
        final_countries = []
        for i in range(0, 20):
            random_country = random.choice(flag_file_names)
            final_countries.append(random_country)
        if CommunicationAPI.detect_duplicates(final_countries):
            CommunicationAPI.create_flag_list()
        return final_countries

    def get(self) -> tuple[dict[str, list], int]:
        """
        Method to return a list of the final flags
        :return: a list of the final flags
        :rtype: dict
        """
        return {"final_flags": final_flags}, 200

    def patch(self):
        """
        Method to update the score of the player
        :return: {"score": int, "gameFinished": bool}, int
        """
        args = self.score_patch_args.parse_args()
        player = None

        if args["id"]:
            player = MatchmakingDB.query.filter_by(playerID=args["id"]).first()
        if player is not None:
            if args["score"]:
                player.playerScore = args["score"]

            db.session.commit()

            sec_player_id = player.matchedPlayer
            if sec_player_id:
                sec_player = MatchmakingDB.query.filter_by(playerID=sec_player_id).first()
                if sec_player:
                    return {"score": sec_player.playerScore, "gameFinished": sec_player.gameFinished}, 200

    def post(self):
        """
        Method to update the state of the game - used to finish the game when one player is done
        :return: {"message": "State successfully set"}, int
        """
        args_pars = reqparse.RequestParser()
        args_pars.add_argument("gameFinished", type=bool, help="Bool which indicates state of game")
        args_pars.add_argument("playerID", type=int, help="Player ID to identify player in DB")

        args = args_pars.parse_args()
        if args["playerID"]:
            player = MatchmakingDB.query.filter_by(playerID=args["playerID"]).first()
            if player is not None:
                player.gameFinished = True
                db.session.commit()
                return {"message": "State successfully set"}, 200
            else:
                return {"message": "Player not found in DB"}, 500
        else:
            return {"message": "Content not able to indentify"}, 400


class UpdateAPI(Resource):
    def __init__(self):
        self.game_version = 0.2

    def get(self):
        return {"gversion": self.game_version}


class BackupFunctionAPI(Resource):
    def __init__(self):
        pass

    def get(self):
        """
        Method to create a zip file with all backup files
        :return: a zip file
        """

        path = fr'backups\{request.remote_addr}'
        par_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
        directory_path = os.path.join(par_dir, path)

        if os.path.exists(directory_path):
            stream = BytesIO()
            with ZipFile(stream, 'w') as zf:
                for file in glob(os.path.join(directory_path, '*.json')):
                    zf.write(file, os.path.basename(file))
            stream.seek(0)
            return send_file(
                stream,
                as_attachment=True,
                download_name='downloaded_files.zip'
            )

    def post(self):
        pass


class PlayerAPI(Resource):
    def __init__(self):
        self.player_get_args = reqparse.RequestParser()
        self.player_get_args.add_argument("playerID", type=int, help="Player ID - Required")

        self.player_set_data_args = reqparse.RequestParser()
        self.player_set_data_args.add_argument("playerID", type=int, help="Player ID - Required")
        self.player_set_data_args.add_argument("name", type=str, help="Player name - Required")
        self.player_set_data_args.add_argument("avatar", type=str, help="Player country - Required")
        self.player_set_data_args.add_argument("nationality", type=str, help="Player score - Required")

    def put(self):
        """
        Method to return specific player
        :return: {"playerID": int, "name": str, "avatar": str, "nationality": str}, int
        """
        args = self.player_get_args.parse_args()
        if args["playerID"]:
            player = PlayerDB.query.filter_by(playerID=args["playerID"]).first()
            if player is not None:
                playerID = player.playerID
                name = player.playerName
                avatar = player.avatar
                nationality = player.nationality
                print(playerID, name, avatar, nationality)
                return {"playerID": playerID, "name": name, "avatar": avatar, "nationality": nationality}, 200
        else:
            return {"message": "Content not able to identify"}, 400

    def patch(self):
        """
        Method to update specific player
        :return: {"playerID": int, "name": str, "avatar": str, "nationality": str}, int
        """
        args = self.player_set_data_args.parse_args()
        if args["playerID"]:
            player = PlayerDB.query.filter_by(playerID=args["playerID"]).first()
            if player:
                player.playerName = args["name"]
                player.avatar = args["avatar"]
                player.nationality = args["nationality"]
                db.session.commit()

                playerID = player.playerID
                name = player.playerName
                avatar = player.avatar
                nationality = player.nationality
                return {"playerID": playerID, "name": name, "avatar": avatar, "nationality": nationality}, 200

    def post(self):
        """
        Method to add a new player
        :return: {"id": int}, int
        """
        player_id = db.session.query(PlayerDB).count() + 1
        new_entry = PlayerDB(playerID=player_id, playerName=None,
                             avatar=None, nationality=None)
        db.session.add(new_entry)
        db.session.commit()

        return {"id": player_id}, 200


@app.route('/ping')
def ping_server():
    """
    Method to check if the server is online
    """
    return {"server_online": True}, 200


api.add_resource(Matchmaking, "/matchmaking")
api.add_resource(CommunicationAPI, "/communicationAPI")
api.add_resource(UpdateAPI, "/update")
api.add_resource(BackupFunctionAPI, "/backup")
api.add_resource(PlayerAPI, "/player")

if __name__ == "__main__":
    app.run(host="0.0.0.0")

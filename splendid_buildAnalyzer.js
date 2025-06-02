"use strict";
var __awaiter = (this && this.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
var __generator = (this && this.__generator) || function (thisArg, body) {
    var _ = { label: 0, sent: function() { if (t[0] & 1) throw t[1]; return t[1]; }, trys: [], ops: [] }, f, y, t, g = Object.create((typeof Iterator === "function" ? Iterator : Object).prototype);
    return g.next = verb(0), g["throw"] = verb(1), g["return"] = verb(2), typeof Symbol === "function" && (g[Symbol.iterator] = function() { return this; }), g;
    function verb(n) { return function (v) { return step([n, v]); }; }
    function step(op) {
        if (f) throw new TypeError("Generator is already executing.");
        while (g && (g = 0, op[0] && (_ = 0)), _) try {
            if (f = 1, y && (t = op[0] & 2 ? y["return"] : op[0] ? y["throw"] || ((t = y["return"]) && t.call(y), 0) : y.next) && !(t = t.call(y, op[1])).done) return t;
            if (y = 0, t) op = [op[0] & 2, t.value];
            switch (op[0]) {
                case 0: case 1: t = op; break;
                case 4: _.label++; return { value: op[1], done: false };
                case 5: _.label++; y = op[1]; op = [0]; continue;
                case 7: op = _.ops.pop(); _.trys.pop(); continue;
                default:
                    if (!(t = _.trys, t = t.length > 0 && t[t.length - 1]) && (op[0] === 6 || op[0] === 2)) { _ = 0; continue; }
                    if (op[0] === 3 && (!t || (op[1] > t[0] && op[1] < t[3]))) { _.label = op[1]; break; }
                    if (op[0] === 6 && _.label < t[1]) { _.label = t[1]; t = op; break; }
                    if (t && _.label < t[2]) { _.label = t[2]; _.ops.push(op); break; }
                    if (t[2]) _.ops.pop();
                    _.trys.pop(); continue;
            }
            op = body.call(thisArg, _);
        } catch (e) { op = [6, e]; y = 0; } finally { f = t = 0; }
        if (op[0] & 5) throw op[1]; return { value: op[0] ? op[1] : void 0, done: true };
    }
};
Object.defineProperty(exports, "__esModule", { value: true });
var sdfz_demo_parser_1 = require("sdfz-demo-parser");
// Load the full build.
var _ = require("lodash");
// Load the core build.
var _ = require("lodash/core");
// Load the FP build for immutable auto-curried iteratee-first data-last methods.
var fp = require("lodash/fp");
(function () { return __awaiter(void 0, void 0, void 0, function () {
    var gameDir, gameFile, path, parser, demo, teamStats, infos, playerInfos;
    var _a;
    return __generator(this, function (_b) {
        switch (_b.label) {
            case 0:
                gameDir = "/home/ryan/.local/state/Beyond All Reason/demos/";
                gameFile = "2025-05-30_14-58-54-554_All That Glitters v2_2025.04.04.sdfz";
                path = gameDir + "" + gameFile;
                parser = new sdfz_demo_parser_1.DemoParser();
                return [4 /*yield*/, parser.parseDemo(path)];
            case 1:
                demo = _b.sent();
                teamStats = (_a = demo.statistics) === null || _a === void 0 ? void 0 : _a.teamStats;
                infos = demo.info;
                /*for(const key in teamStats)
                {
                    console.log(key, teamStats[key])
                }*/
                console.log(infos.players);
                getPlayerStatsFrameByFrame(1, infos.players, teamStats);
                playerInfos = infos.players;
                return [2 /*return*/];
        }
    });
}); })();
function calculateResourceDiff(obj1, obj2) {
    var diffObject = {};
    for (var key in obj2) {
        if (Object.prototype.hasOwnProperty.call(obj2, key) && typeof obj2[key] === "number") {
            var originalKey = key; // Cast to keyof ResourceStats
            var value1 = obj1[originalKey];
            var value2 = obj2[originalKey];
            if (typeof value1 === "number" && typeof value2 === "number") {
                var diff = value2 - value1;
                diffObject["".concat(originalKey, "Diff")] = diff;
            }
        }
    }
    return diffObject;
}
function getPlayerStatsFrameByFrame(playerId, info, stats) {
    var playerStats = stats[playerId];
    var playerInfo = null;
    //console.log("playerStats:", playerStats);
    //console.log("playerInfo:", info.find(info => info.playerId === playerId));
    var energy_per_frame = 0;
    var lastFrame = playerStats[0];
    for (var i = 0; i < playerStats.length; i++) {
        var frame = playerStats[i];
        var thisFrame = calculateResourceDiff(lastFrame, frame);
        //console.log(thisFrame);
        var tinyFrame = _.pick(thisFrame, "metalUsedDiff", "energyUsedDiff", "metalProducedDiff", "energyProducedDiff", "metalExcessDiff", "energyExcessDiff", "damageDealtDiff", "damageReceivedDiff");
        //console.log(tinyFrame);
        var currentMetal = 1000 + frame["metalProduced"] + frame["metalReceived"] - frame["metalUsed"] - frame["metalSent"] - frame["metalExcess"];
        var currentEnergy = 1000 + frame["energyProduced"] + frame["energyReceived"] - frame["energyUsed"] - frame["energySent"] - frame["energyExcess"];
        var gameSeconds = (i * 15) % 60;
        var gameMinutes = Math.floor(i / 4);
        console.log(gameMinutes + ":" + (gameSeconds === 0 ? "00" : gameSeconds) + "| currentMetal: " + currentMetal + " :: currentEnergy: " + currentEnergy);
        lastFrame = frame;
    }
}

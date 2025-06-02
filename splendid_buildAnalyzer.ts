import { DemoParser } from "sdfz-demo-parser";
// Load the full build.
var _ = require("lodash");
// Load the core build.
var _ = require("lodash/core");
// Load the FP build for immutable auto-curried iteratee-first data-last methods.
var fp = require("lodash/fp");


(async () => {
    //const demoPath = "./test/test_replays/20201219_003920_Altored Divide Bar Remake 1_104.0.1-1707-gc0fc18e BAR.sdfz";

    const gameDir = "/home/ryan/.local/state/Beyond All Reason/demos/";
    const gameFile = "2025-05-30_14-58-54-554_All That Glitters v2_2025.04.04.sdfz";
    const path = gameDir + "" + gameFile;
    const parser = new DemoParser();

    const demo = await parser.parseDemo(path);

    //  console.log(demo.statistics?.teamStats; // [Fx]Jazcas
    const teamStats = demo.statistics?.teamStats;
    const infos = demo.info;
    /*for(const key in teamStats)
    {
        console.log(key, teamStats[key])
    }*/
    console.log(infos.players);

    getPlayerStatsFrameByFrame(1, infos.players, teamStats);
    let playerInfos = infos.players;



})();


type ResourceStats = {
    frame: number;
    metalUsed: number;
    energyUsed: number;
    metalProduced: number;
    energyProduced: number;
    metalExcess: number;
    energyExcess: number;
    metalReceived: number;
    energyReceived: number;
    metalSent: number;
    energySent: number;
    damageDealt: number;
    damageReceived: number;
    unitsProduced: number;
    unitsDied: number;
    unitsReceived: number;
    unitsSent: number;
    unitsCaptured: number;
    unitsOutCaptured: number;
    unitsKilled: number;
    [key: string]: number; // Index signature to allow arbitrary string keys with number values
  };

type ResourceDiff = {
    [key: string]: number;
};
// Interface for player general information
interface PlayerInfo {
    playerId: number;
    userId: number;
    name: string;
    countryCode: string;
    rank: number;
    skillclass: string | undefined;
    skillUncertainty: number;
    skill: string;
    isFromDemo: boolean | undefined;
    clanId: number | undefined;
    teamId: number;
    rgbColor: { b: number; g: number; r: number };
    allyTeamId: number;
    handicap: number;
    faction: string;
    startPos: { x: number; y: number; z: number };
  }

  // Interface for player frame statistics (differences over a frame)
  interface PlayerFrame {

    playerId: number; // Index signature for dynamic access to  stats
    stats: {


        metalUsed: number;
        energyUsed: number;
        metalProduced: number;
        energyProduced: number;
        metalExcess: number;
        energyExcess: number;
        metalReceived: number;
        energyReceived: number;
        metalSent: number;
        energySent: number;
        damageDealt: number;
        damageReceived: number;
        unitsProduced: number;
        unitsDied: number;
        unitsReceived: number;
        unitsSent: number;
        unitsCaptured: number;
        unitsOutCaptured: number;
        unitsKilled: number;
    }

  }

  // Interface for the output of the ranking function
  interface PlayerRankingsOutput {
    rankings: { [statName: string]: number[] }; // Key: stat name, Value: array of playerIds in rank order
    highlightedPlayerRelativePositions: { [statName: string]: number }; // Key: stat name, Value: relative position (0-1)
  }


function calculateResourceDiff(
    obj1: ResourceStats,
    obj2: ResourceStats
): ResourceDiff {
    const diffObject: ResourceDiff = {};

    for (const key in obj2) {
        if (Object.prototype.hasOwnProperty.call(obj2, key) && typeof obj2[key] === "number") {
            const originalKey = key as keyof ResourceStats; // Cast to keyof ResourceStats
            const value1 = obj1[originalKey];
            const value2 = obj2[originalKey];

            if (typeof value1 === "number" && typeof value2 === "number") {
                const diff = value2 - value1;
                diffObject[`${originalKey}Diff`] = diff;
            }
        }
    }
    return diffObject;
}


function getPlayerStatsFrameByFrame(playerId, info, stats) {
    const playerStats = stats[playerId];
    const playerInfo = null;


    //console.log("playerStats:", playerStats);
    //console.log("playerInfo:", info.find(info => info.playerId === playerId));

    let energy_per_frame = 0;
    let lastFrame = playerStats[0];

    for (var i = 0;i < playerStats.length;i++) {
        const frame = playerStats[i];
        const thisFrame = calculateResourceDiff(lastFrame, frame);
        //console.log(thisFrame);
        const tinyFrame = _.pick(thisFrame, "metalUsedDiff", "energyUsedDiff", "metalProducedDiff", "energyProducedDiff", "metalExcessDiff", "energyExcessDiff", "damageDealtDiff", "damageReceivedDiff");

        //console.log(tinyFrame);
        const currentMetal = 1000 + frame["metalProduced"] + frame["metalReceived"] - frame["metalUsed"] - frame["metalSent"]  - frame["metalExcess"];
        const currentEnergy = 1000 + frame["energyProduced"] + frame["energyReceived"] - frame["energyUsed"] - frame["energySent"]  - frame["energyExcess"];
        const gameSeconds = (i * 15) % 60;
        const gameMinutes = Math.floor(i / 4);
        console.log(gameMinutes + ":" + (gameSeconds === 0 ? "00" : gameSeconds) + "| currentMetal: " +  currentMetal + " :: currentEnergy: " + currentEnergy);
        lastFrame = frame;
    }
}

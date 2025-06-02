import { DemoParser } from "sdfz-demo-parser";

(async () => {
    //const demoPath = "./test/test_replays/20201219_003920_Altored Divide Bar Remake 1_104.0.1-1707-gc0fc18e BAR.sdfz";

    const gameDir = "/home/ryan/.local/state/Beyond All Reason/demos/";
    const gameFile = "2025-05-30_14-58-54-554_All That Glitters v2_2025.04.04.sdfz"
    const path = gameDir + "" + gameFile;
    const parser = new DemoParser();

    const demo = await parser.parseDemo(path);

//  console.log(demo.statistics?.teamStats; // [Fx]Jazcas
    const teamStats = demo.statistics?.teamStats;
    const infos = demo.info;
//    console.log(teamStats) 
    /*for(const key in teamStats)
    {
        console.log(key, teamStats[key])
    }*/

    getPlayerStats(3, infos.players, teamStats);

    //console.log(infos);

})();

function getPlayerStats(playerId, info, stats)
{
    const playerStats = stats[playerId];
    const playerInfo = null;


    console.log("playerStats:", playerStats)
    console.log("playerInfo:", info.find(info => info.playerId === playerId));

}

https://www.beyondallreason.info/unit/armwin, https://www.beyondallreason.info/unit/armck,

https://www.beyondallreason.info/unit/armsolar,[https://www.beyondallreason.info/unit/armadvsol](https://www.beyondallreason.info/unit/armadvsol),

I want to create a python script that project a system forward a couple of steps to compare available options based on current conditions.

At any second, a player has current_metal(def:1000)/metal_storage(def1000), current_energy(def:1000)/energy_storage(def:1000), and an amount of build power as the sum of their constructors build power which could be independant but we will treat as uniform, starting with a 300BP commander.

There are [https://www.beyondallreason.info/unit/armmex](https://www.beyondallreason.info/unit/armmex) mex locations, generating 1.825 metal per second. There are a fixed number of available mexs, and they have a distance which means a working unit may need to spend distance/walkspeed seconds of 0 build power as an additional building cost.
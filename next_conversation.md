# Next conversation — carry-forward doc

Holder for the next session. The script below is the BAR economy explanation in my
own words, aimed at someone who plays but hasn't thought about the economy as a
system. No player names, no game files, no dates — it should read the same in six
months. Anything stated as a measurement was measured off replays, not guessed.

---

## Script: explaining BAR economy to darthbudhha

### Start with three levers, not one

Everything in this game is three resources and the conversions between them. Metal,
energy, and build power. Metal is the one you actually want. Energy exists to let you
spend metal. Build power exists to let you spend it *fast enough*.

When people say they're "eco-ing" they usually mean one of those three and don't say
which. That's where most of the confusion comes from. If you're metal-stalled, more
energy doesn't help you. If you're energy-stalled, more mexes don't help you. If your
bank is full and climbing, neither helps — you don't have enough build power to spend
what you're already making.

So the first question in any position is always: which of the three am I short of
right now, and which will I be short of in sixty seconds.

### Metal extractors are the best purchase in the game, by a lot

A mex costs 50 metal and 500 energy. Convert that energy at the standard rate and the
whole thing is worth about 57 metal. It makes roughly 1.8 metal per second on a normal
spot. So it pays itself back in about 31 seconds.

Nothing else is close. A solar is 155 metal for 20 energy per second. A wind is 40
metal for whatever the map gives you. Those are fine purchases, but they're
*infrastructure* — they exist so you can afford the mexes and the things after them.

That's the whole reason the opening looks the way it does. You take every mex you can
reach, as early as you can reach it, and you buy exactly as much energy as you need to
keep doing that.

### The four steps, in order

If you want the whole game in four moves, it's this.

**One: gather the low hanging fruit.** All the T1 metal that isn't contested. The spots
you can reach without fighting for them. This is pure income and it's the cheapest
income you will ever buy, so there is no argument about doing it first.

**Two: defend it.** Fruit you can't hold isn't income, it's a donation. This doesn't
mean turtling — it means whatever is actually sufficient for the threat that exists.
Sometimes that's a couple of defences on the exposed spots, sometimes it's just units
being nearby, sometimes it's nothing because nobody can reach you yet. But you have to
decide it deliberately, because losing a mex costs you the mex *and* everything you
would have built with what it was going to make.

**Three: scale energy and build power until you can actually use that metal income.**
You now have metal arriving. If your bank is climbing, you are wasting it. Energy and
build power exist to convert metal income into things on the map, and until they're
large enough to consume everything the mexes produce, they are the only correct
purchase. This is the step people skip, and it's why you see players with ten mexes and
a full bank doing nothing.

**Four: decide whether to keep scaling, or to spend on a direction.** Once you *can*
consume your income, you have a real choice for the first time. More economy, or units,
or tech, or map. There's no default answer — that's the point of the step. But you
can't make the choice honestly until step three is done, because before that "more
economy" is not a strategy, it's just fixing a leak.

### Step four is a shape, not a number

Here's the part that took me longest to get.

The target economy has a *shape* — how much build power and how much energy generation
you want relative to your metal income — and that shape is a strategic decision, not a
formula. Two players with identical metal income should build differently depending on
what they expect the rest of the game to look like.

**If you don't expect payments**, you go T2 later and you build a higher base income
first. Nobody is funnelling you metal, so your throughput ceiling is your own income.
There's no point owning build power you can't feed. You take the slower road, arrive at
T2 with a bigger economy underneath you, and then you're the one who can support the
team rather than needing support.

**If you do expect payments**, you invert it. You build more energy and more build power
than your own metal income justifies, on purpose, because metal is going to arrive from
your teammates and be funnelled through your T2 lab. Your job is to be able to spend
more than you personally make. Build power you can't feed yet is not waste in that case,
it's the whole point — it's capacity waiting for the metal that's coming.

So the question behind step four isn't "how much economy do I want". It's *how much
metal am I going to be asked to convert, and do I have the energy and build power to
convert it at that rate*. Size to expected throughput, not to your own income.

That's also the cleanest way to say what a tech player is. A tech player is someone who
has agreed to be a throughput bottleneck for the team's metal, and has built the shape
that lets them handle it.

### The opening is a race to a breakpoint, not a build order

Here's the way I actually think about it.

Step one: *these are the mexes available to me*. Not "seven mexes", not "the standard
build" — look at the map, look at your spawn, and count the spots you can realistically
hold. On a normal position that's three you can basically touch, and another three or
four you have to walk to.

Step two: until every one of those mexes has a worker on it or at least walking toward
it, your build priority is whatever gets you to that state fastest. That means energy
so you can afford workers, and workers so you can claim spots. Nothing else. Not units,
not defence, not tech. Energy into workers into mex coverage.

Step three is the breakpoint: every mex is claimed or has someone en route, and you know
when they'll all be done. That's the moment the opening ends.

The mistake — and I've done it on purpose to measure it — is grabbing mexes too early
with the commander. If you walk your commander down the mex line claiming spots, you
delay your factory, which delays your workers, which means the far mexes get claimed by
one slow worker instead of three in parallel. I ran that variant against the normal one.
Walking the line claimed the fourth and fifth mex a full minute earlier and still
reached full coverage over a minute *later*. Earlier spots, later breakpoint. The
factory is the thing you're actually buying.

### Solar versus wind is a timing question, not a value question

Wind is the better building. Cheaper per energy, and you need less build power to get
the same total energy, which matters more than people think.

Solar's advantage is entirely at the front. A solar costs no energy to build. A wind
costs energy you don't have yet. So in the first minute or two, solar gives you energy
*sooner* — call it fifteen to twenty-five seconds sooner in practice — and those seconds
buy you a worker, which buys you a mex, which is the best purchase in the game.

Say it precisely and it stops being an argument about efficiency at all. **A mex costs 500
energy.** A wind costs 175 energy to erect. A solar costs none. So in the window where
your energy income is small, every turbine you put up is energy you did not spend
claiming a metal spot. Solar doesn't out-earn wind. Solar gets out of the way of the
mexes.

That energy tax is real, but on its own it is **not** what decides the opening. I had to
simulate it twice to find that out, and the first attempt was wrong in an instructive way.

The first version forced both branches through an identical build order and only swapped
the generator. It said solar reached seven mexes ten seconds sooner. That answer was an
artifact. Holding the plan identical made the wind branch sit on hundreds of banked metal
it would obviously have spent — no player carries a bank like that. Two openings with
different resource situations make different builds; that is the whole point.

The second version gives both branches the same *rule* instead of the same build, and
lets builders work concurrently so a worker can walk to a spot while the commander builds
at home. The rule is the one above: buy energy when the crew's draw would outrun income,
buy build power when metal arrives faster than the crew can spend it, otherwise take the
next spot. Generator counts and build-power timing become outputs, not inputs.

Run that way, at the map's real average wind, **the two tie**. Seven mexes at the same
second. What differs is what each one is holding when it gets there: solar has spent its
metal down to nothing and owns more energy infrastructure, wind has more build power,
more energy income *and* about 870 metal still spare. On those numbers wind should be the
better opening, which is not what I actually play.

So the real shape is: solar early because it's fast, wind later because it's efficient,
and then — this is the part people skip — you reclaim the solars and build wind on top.
You get the full metal back. It's not a sunk cost. The solar was a loan against time.

### Where the break-even actually sits

The theory is easy and it is misleading. Price both in metal at the standard conversion.
Solar is 155 metal for 20 energy per second, so 7.75 metal per point of income. Wind is
40 metal plus 175 energy, which is 42.5 metal all-in, for whatever the map gives. Set
them equal and wind is the cheaper economy above **5.5 energy per second**. By that
number wind should win on essentially every map in the game.

So what actually makes solar the right opening? **Building count.**

At the map's average wind you need roughly twice as many turbines as panels for the same
income — the simulation settles on about 21 turbines against 11 panels. Every one of
those is a builder walking to open ground and placing something. The model above charged
nothing for that, which is why it called a tie. Put any placement cost on it at all and
the picture flips, because the cost lands on wind twice as often:

| Seconds to place each generator | Solar to 7 mex | Wind to 7 mex |
|---|---|---|
| 0 (free, unrealistic) | 183 | 183 |
| 2 | 177 | 191 |
| 4 | 182 | 199 |
| 6 | 186 | 207 |

Two seconds of placement is enough to hand solar a fourteen second lead. Four seconds
makes it eighteen.

That is the reconciliation. Wind is genuinely the cheaper economy and the pure metal
maths says so above about 5.5 energy per second, which is nearly every map. The energy
tax narrows that but does not overturn it. What overturns it in the opening is that wind
buys its cheapness in small pieces, and small pieces cost builder attention you do not
have at two minutes.

Which is also exactly why the conversion later is right. By the four minute mark you have
a crew and spare build power, placing twenty turbines is cheap, and wind's efficiency
finally arrives without the placement penalty. Solar wins the opening because it is
*concentrated*, not because it is better.

One more thing worth knowing: real wind varies, and that variance is nearly free on
average but expensive in spread. Across a dozen simulated games on the same map the median
finish barely moved, about two seconds, but the range ran from 148 to 189 seconds. So the
wind opening is not worse on average, it is less predictable, and in the opening you are
paying for predictability.

I checked this against my own games and it's not a plan I follow, it's a habit I already
have: every solar gets reclaimed somewhere in the three-and-a-half to four-and-a-half
minute window, consistently, across every variation I tried.

### How wind actually works, because almost nobody knows this

Wind is not a random number per tick. It's a two-dimensional vector.

Every fifteen seconds the engine picks a new vector by adding a random offset to the
current one, then clamps the new vector's length into the map's range. Over those
fifteen seconds the live vector slides smoothly from the old one to the new one. Your
turbine output is the length of that vector — the distance from the centre to the tip.

Two things follow from that.

First, the destination is decided the instant the window opens. So if you watch which
way the wind is drifting in the first moment of a window, you already know where it's
going to end up. You can see a lull coming fifteen seconds out.

Second, and this is the one that changes decisions: the average wind on a map is **not**
the midpoint of its range. The vector wanders around far from the origin much more than
it sits near it. On a map with a zero-to-sixteen range, the midpoint says eight energy
per second. The real average is closer to twelve. I measured it off recorded games and
got just under twelve over a full game and about twelve and a half over the first
fifteen minutes.

If you've been valuing wind at the midpoint, you've been undervaluing it by half. That
moves the solar-versus-wind break-even a long way.

### After the breakpoint: the spending cascade

Once every mex is covered, the question changes from "what do I build" to "am I actually
spending what I make". In order:

Am I spending my current metal? If the bank is climbing, I'm not. Can I get the bank to
zero and hold it near zero? That's the goal state — everything you own is working.

If I can't spend it, the problem is build power or energy, and I add whichever is
binding. More workers or nano if build power is short. More energy if the builders are
there but starving.

If I'm genuinely energy-rich and want to bank it, that splits two ways. Advanced solar
is the greedier option — more energy per structure, better long-run. Energy storage is
the safety option — it smooths the wind lulls and lets converters run through them. I
aim for a split, and I lean greedier when I actually know my energy income rather than
guessing at it. Greed is fine when the number is known.

And the standing background task, once you have wind income, is converting the early
solars into wind.

### Front player versus tech player

The *ordering* above is the same whatever you're spending the metal on — cover the mexes,
then make sure you can consume the income, then choose. That's the point of thinking
about it this way: it separates the sequence from the plan.

What differs by role is the shape you're aiming at, which is the step four question
again. A front player can walk forward and take the contested spots, so they get more
mexes but have to spend metal on units to hold them — their metal has somewhere to go
immediately, so they need less stored capacity. A tech player takes the safe spots and
spends into an advanced factory, advanced constructors and upgraded extractors, and
sizes their energy and build power to the metal they expect to be handed, not just the
metal they make.

There's a middle case that's worth naming: as a tech player you can often walk forward
to the sixth and seventh spot anyway, because nobody's contesting them yet. You get the
front player's mex count with the tech player's spending. That's the position I test
most.

The end of that line is usually blowing up the commander deliberately once its build
power is no longer the bottleneck, and reclaiming the wreck.

### Reclaim, since it comes up

Reclaiming a finished building gives you back one hundred percent of its metal cost. Not
a fraction. A solar gives exactly 155, a wind exactly 40, an advanced solar exactly 350.
I verified this across several games and the only ones that came back short were the
ones where the reclaim got interrupted partway.

It's also not instant. The engine hands you the metal at a steady rate over the whole
reclaim, which takes a second or so for small things and longer for big ones. So it
shows up as a sustained trickle, not a lump.

Practical consequence: reclaim is a real income source, not a rounding error. In a
normal game it's somewhere between a tenth and a quarter of all the metal a player
touches, and that's before counting wreckage.

---

## For the next session

Open threads, in the order they matter:

1. **Wind-versus-solar break-even, properly.** All the inputs now exist: real wind per
   game, real mex spot positions and walk distances, real build timings. What's missing
   is the model that says "at wind X, solar stops being worth it after Y seconds".
2. **Time-resolved reclaim.** Reclaim value per unit is measurable but only as a
   lifetime total per unit. Getting it per minute needs periodic sampling.
3. **Per-team resources in short replays.** Structure counts and timings come out fine,
   but income isn't sampled early enough to rank builds by output.
4. The opportunity-cost model this was all for: metal gained versus lost over time as a
   function of what the bank was doing.

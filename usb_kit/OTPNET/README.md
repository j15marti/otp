# OTPNET: private messages nobody can crack

OTPNET lets you and your friends send each other messages that **no one else
can ever read**. That includes hackers, companies, governments, and future
supercomputers or AI.

## How it works, in plain words

Imagine you and a friend each have an identical notebook filled with random
scribbles, and nobody else in the world has a copy. To send a secret, you
scramble your message using the next fresh page, then tear that page out. Your
friend unscrambles it with the same page from their notebook, then tears theirs
out too. Without that page, the message is just noise.

* **The notebook** is a file of pure randomness on your USB drive, called a *pad*.
* **You make the copies together, in person**, by plugging both USB drives into
  one computer. That's why nobody else can have a copy.
* **Each page is used once and then erased.** OTPNET handles all of this for you.
* **Your scrambled message travels through three volunteer computers** (called
  *relays*) on its way to your friend. None of them can read it, and none of
  them knows both who sent it and who receives it.
* **Relays are paid a few tokens** for each message they carry. You start with
  free tokens in your wallet.

> **Please note:** this is an early test version. Try it, but don't rely on it
> yet for anything truly important.

---

## What you need

* **A USB drive** (any size; 8 GB or more is plenty to start).
* **A computer with Python**, a free program OTPNET runs on:
  * **Windows:** get it from [python.org/downloads](https://www.python.org/downloads/).
    While installing, **tick "Add python.exe to PATH"**.
  * **Mac:** get it from [python.org/downloads](https://www.python.org/downloads/).
  * **Linux:** usually already installed.

  If you skip this, OTPNET opens the download page for you the first time.
* **A friend with their own USB drive**, and a chance to meet them in person
  once.
* **A network address.** This comes from whoever runs your OTPNET network: a
  friend, a club, or your organisation. Just trying it out on one computer?
  You don't need one.

---

## Step 1: Put OTPNET on your USB drive

1. Plug in your USB drive.
2. Unzip the OTPNET download. You'll get a folder called **`OTPNET`**.
3. Drag the **`OTPNET`** folder onto your USB drive.

## Step 2: Open OTPNET

Open the `OTPNET` folder on your USB drive and double-click the Start file for
your computer:

| Your computer | Double-click this |
|---|---|
| **Windows** | `Start OTPNET (Windows).bat` |
| **Mac** | `Start OTPNET (Mac).command` |
| **Linux** | `Start OTPNET (Linux).sh` (choose "Run in Terminal" if asked) |

A window with a simple menu opens. You choose things by **typing a number and
pressing Enter**.

**The first time only:**

* **Mac:** if it says the file "can't be opened", right-click the file, choose
  **Open**, then click **Open** again.
* **Windows:** if a blue "Windows protected your PC" box appears, click
  **More info**, then **Run anyway**.
* OTPNET may take a minute to finish installing. It does this from the USB
  drive itself, so no internet is needed.

## Step 3: Set up your drive (once)

OTPNET asks three things:

1. **A name** your friends will see, e.g. `alice`.
2. **The network address.** Type what your network organiser gave you, or just
   press Enter to try OTPNET on this computer.
3. **Will friends on other computers send to this drive?** Press Enter (No) if
   you're just trying it out. Answer Yes if you'll be messaging people on other
   computers. Your organiser will tell you what address to type.

## Step 4: Add a friend (do this together, in person)

1. Sit down together at one computer and plug in **both** USB drives.
2. On your drive, open OTPNET and choose **4) Add a contact**.
3. When asked, **drag your friend's USB drive** (or their `OTPNET` folder) into
   the window and press Enter.
   * If their drive doesn't have OTPNET yet, OTPNET offers to **copy itself
     onto it** and set it up. Just answer the questions with your friend.
4. Pick a size. **100 MB** is plenty for most people: about 20,000 messages
   each way.
5. Wait for "Done!" Your friend can now take their drive home.

You only meet once per friend. When you eventually use up the pad, meet again
and add them again.

## Step 5: Send and read messages

* **To send:** choose **1) Send a message**, pick your friend, type a subject,
  then type your message. When you're finished, **type a single dot `.` on its
  own line** and press Enter. You can attach files too.
* **To read:** choose **2) Read my messages** and pick one by its number.
  Attached files are saved on your USB drive; OTPNET shows you where.

**Important: messages only arrive while OTPNET is open.** Your friend's OTPNET
must also be open when you send them something. If it isn't, OTPNET tells you
the message wasn't delivered. Just try again later.

---

## Your wallet (tokens)

Choose **3) Wallet** to see your tokens.

* **What tokens are for:** each message pays the three volunteer computers
  that carry it, about **1.5 tokens per message** in total.
* **Where they come from:** your wallet starts with **free welcome tokens**.
  You can get more from a friend, or earn them by running a relay (below).
* **You only pay for messages that arrive.** If a relay doesn't pass your
  message on, its fee comes back to your wallet within about 5 minutes.
* **Send tokens to someone:** in the Wallet screen choose **Send tokens to
  someone**, type their wallet name (the same as their OTPNET name) and the
  amount, and confirm.
* **Back up your wallet:** your tokens are tied to a key stored on your USB
  drive. Choose **Back up my wallet key** to save a copy to another drive.
  **Keep that copy private:** anyone who has it can spend your tokens.

## Earn tokens: help carry messages

Choose **6) Run a relay to earn tokens**. Your computer then carries other
people's scrambled messages, and you earn a small fee for each one. It can't
read them, and it can't tell who is talking to whom. Leave the window open as
long as you like; press **Ctrl + C** to stop. Your earnings collect in the
relay's own wallet. To move them into yours, open **3) Wallet** and choose
**Move my relay earnings into this wallet**.

---

## Keeping yourself safe

* **Treat your USB drive like your house keys.** Anyone who gets it can read
  the messages your friends send you from then on.
* **Lost your drive?** Tell your friends straight away, and meet up to add
  each other again with a new pad.
* **Never copy the pad files** (the `data/pads` folder) anywhere. The whole
  point is that only two copies exist.
* **Back up your wallet key**, not your pads.

## Something not working?

| Problem | What to do |
|---|---|
| "Python is not installed" | Install it from [python.org/downloads](https://www.python.org/downloads/) (Windows: tick "Add python.exe to PATH"), then double-click Start again. |
| "Network NOT reachable" or "can't reach the network" | Check your internet, and that the network address is right (**7) Check my setup** shows it). Ask your organiser whether the network is running. |
| "NOT delivered" | Your friend's OTPNET is probably closed. Ask them to open it, then send again. |
| "couldn't open your inbox … already running" | OTPNET is already open in another window. Use that one, or close it. |
| "Not enough space" when adding a friend | Pick a smaller size, or free up space on either drive. |
| "need at least 3 relays" | The network needs more volunteers right now. Try later, or run a relay yourself. |
| Pad running low | Shown under **5) My contacts**. Meet your friend and add them again. |

---

## Want to see it all work first?

Run the built-in demonstration. It creates two pretend users, a small network
and three relays on your computer, sends messages between them, and checks
that everything works. Open a terminal in the `OTPNET` folder and type:

```
python demo.py
```

## For technical users

Command-line usage, running a network, the security design and the known
limitations are in **[TECHNICAL.md](TECHNICAL.md)**.

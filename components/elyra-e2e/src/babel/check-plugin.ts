import {goto, label} from "./goto.ts";
function loop() {
    var i = 0;


    start:
        i = i + 1;
    console.log(i);
    if (i == 10) goto(end);
    goto(start);

    end:
        console.log("all done");
}

loop();

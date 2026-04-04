function goToStep(stepNum) {
    const isGenerated = document.getElementById('step-3-container') !== null;
    
    // Validate if trying to move from step 1 to 2/3
    if (stepNum > 1 && document.getElementById('step-1-container').style.display !== 'none') {
        if (!document.querySelector('input[name="subject"]').checkValidity() || !document.querySelector('input[name="exam_title"]').checkValidity()) {
            document.querySelector('#generator-form').reportValidity();
            return;
        }
    }

    // Hide all steps
    document.getElementById('step-1-container').style.display = 'none';
    if(document.getElementById('step-2-container')) document.getElementById('step-2-container').style.display = 'none';
    if(document.getElementById('step-3-container')) document.getElementById('step-3-container').style.display = 'none';

    // Show target step
    if (stepNum === 1) {
        document.getElementById('step-1-container').style.display = 'block';
    } else if (stepNum === 2) {
        if(document.getElementById('step-2-container')) document.getElementById('step-2-container').style.display = 'block';
    } else if (stepNum === 3) {
        if(document.getElementById('step-3-container')) document.getElementById('step-3-container').style.display = 'block';
    }

    // Update stepper visuals
    updateStepperVisuals(stepNum, isGenerated);
}

function updateStepperVisuals(currentStep, isGenerated) {
    // Reset all
    document.getElementById('indicator-1').className = 'step step-indicator';
    document.getElementById('indicator-2').className = 'step step-indicator';
    document.getElementById('indicator-3').className = 'step step-indicator';
    
    document.getElementById('icon-1').style.cssText = 'background:#1F2937;color:var(--text-muted);';
    document.getElementById('icon-2').style.cssText = 'background:#1F2937;color:var(--text-muted);';
    document.getElementById('icon-3').style.cssText = 'background:#1F2937;color:var(--text-muted);';
    
    document.getElementById('line-1').classList.remove('active');
    document.getElementById('line-2').classList.remove('active');

    if (currentStep === 1) {
        document.getElementById('indicator-1').classList.add('active');
        document.getElementById('icon-1').style.cssText = 'background:var(--neon-cyan);color:black;';
        if(isGenerated) {
            document.getElementById('indicator-2').classList.add('completed');
            document.getElementById('indicator-3').classList.add('completed');
        }
    } else if (currentStep === 2) {
        document.getElementById('indicator-1').classList.add('completed');
        document.getElementById('indicator-2').classList.add('active');
        document.getElementById('icon-2').style.cssText = 'background:rgba(255,255,255,0.05);color:white;';
        document.getElementById('line-1').classList.add('active');
        if(isGenerated) {
            document.getElementById('indicator-3').classList.add('completed');
        }
    } else if (currentStep === 3) {
        document.getElementById('indicator-1').classList.add('completed');
        document.getElementById('indicator-2').classList.add('completed');
        document.getElementById('indicator-3').classList.add('active');
        document.getElementById('icon-3').style.cssText = 'background:rgba(255,255,255,0.05);color:white;';
        document.getElementById('line-1').classList.add('active');
        document.getElementById('line-2').classList.add('active');
    }
}

function goToStep1() { goToStep(1); }
function goToStep2() { goToStep(2); }

window.addEventListener('DOMContentLoaded', () => {
    // Sync ranges
    const valTwo = document.querySelector('.design-range.purple');
    const valFive = document.querySelector('.design-range.green');
    const valTen = document.querySelector('.design-range');
    if(valTwo) document.getElementById('cbx-two-mark').checked = (valTwo.value > 0);
    if(valFive) document.getElementById('cbx-five-mark').checked = (valFive.value > 0);
    if(valTen) document.getElementById('cbx-ten-mark').checked = (valTen.value > 0);

    // Parse Paper if it exists
    const rawEl = document.getElementById('raw_generate_text');
    if (rawEl) {
        const text = rawEl.innerText;
        const lines = text.split('\n');
        let html = '';
        let currentSection = '';
        let qNumber = 0;

        for (let i = 0; i < lines.length; i++) {
            let line = lines[i].trim();
            if (!line) continue;

            if (line.startsWith('Section') || line.startsWith('QUESTION PAPER')) {
                currentSection = line;
                continue;
            }

            // Look for Question: ^\d+\.
            const qMatch = line.match(/^(\d+)\.\s+(.*)/);
            if (qMatch) {
                qNumber++;
                let questionText = qMatch[2];
                let marks = "2 marks";
                let typeBadge = "Short Answer";
                
                if (currentSection.includes("MCQ")) { typeBadge = "MCQ"; marks = "1 mark"; }
                else if (currentSection.includes("Fill")) { typeBadge = "Fill in Blanks"; marks = "1 mark"; }
                else if (currentSection.includes("5 mark")) { typeBadge = "Detailed Answer"; marks = "5 marks"; }
                else if (currentSection.includes("10 mark") || currentSection.includes("Long")) { typeBadge = "Essay"; marks = "10 marks"; }
                else if (currentSection.includes("2 mark")) { marks = "2 marks"; }

                // Collect rest of question
                let extraLines = [];
                let j = i + 1;
                while(j < lines.length && !lines[j].trim().match(/^(\d+)\./) && !lines[j].trim().startsWith('Section') && !lines[j].trim().startsWith('Instructions')) {
                    if (lines[j].trim()) extraLines.push(lines[j].trim());
                    j++;
                }
                if (extraLines.length > 0) {
                    questionText += "<br><br>" + extraLines.join("<br>");
                }
                i = j - 1;

                html += `
                <div class="q-card">
                    <div class="q-num">${qNumber}</div>
                    <div class="q-content">
                        <div class="q-badges">
                            <div class="badge">${typeBadge}</div>
                            <div class="badge" style="background:transparent; border:1px solid var(--border-color);">${marks}</div>
                        </div>
                        <p class="q-text">${questionText}</p>
                        <div class="q-ans">
                            <span>Expected Answer</span>
                            <p>The student's response will be evaluated based on the core principles taught in the context of this ${typeBadge.toLowerCase()} specific syllabus segment.</p>
                        </div>
                    </div>
                </div>`;
            }
        }
        const parsedContainer = document.getElementById('parsed-paper');
        if(parsedContainer) {
            if(html.trim() === '') parsedContainer.innerHTML = '<p style="color:white; text-align:center;">No valid questions parsed.</p>';
            else parsedContainer.innerHTML = html;
        }
    }
});

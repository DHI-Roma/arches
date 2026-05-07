const backToTop = {
    scrollToTopHandler: function() {
        // Get the button:
        let mybutton = document.getElementById("backToTopBtn");
        if (!mybutton) return;
        
        // Set initial hidden state
        hideButton();
        
        // When the user scrolls down 200px from the top of the document, show the button
        window.onscroll = function() { scrollFunction(); };
        
        function showButton() {
            mybutton.style.opacity = "1";
            mybutton.style.visibility = "visible";
            mybutton.setAttribute("aria-hidden", "false");
            mybutton.setAttribute("tabindex", "0");
        }
        
        function hideButton() {
            mybutton.style.opacity = "0";
            mybutton.style.visibility = "hidden";
            mybutton.setAttribute("aria-hidden", "true");
            mybutton.setAttribute("tabindex", "-1");
        }
        
        function scrollFunction() {
            if (document.body.scrollTop > 200 || document.documentElement.scrollTop > 200) {
                showButton();
            } else {
                hideButton();
            }
        }
    },

    // When the user clicks on the button, scroll to the top of the document
    backToTopHandler: function(data, event) {
        // Handle both click and keyboard events (Enter and Space)
        if (event && event.type === 'keyup') {
            if (event.key !== 'Enter' && event.key !== ' ') {
                return;
            }
        }
        document.body.scrollTop = 0; // For Safari
        document.documentElement.scrollTop = 0; // For Chrome, Firefox, IE, and Opera
        
        // Return focus to main content for accessibility
        const mainContent = document.getElementById('main-content') || document.getElementById('skiptocontent');
        if (mainContent) {
            mainContent.focus();
        }
    },
};

export default backToTop;